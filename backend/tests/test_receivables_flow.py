"""Integracion Sprint 3 Fase 1 (E5-01/E5-02): evento -> Receivable, sin llamada explicita.

Cubre:

- ``workers/sri_transmission.py`` publica ``invoice.authorized`` de forma
  ADITIVA cuando una INVOICE llega a AUTHORIZED (sin depender de MinIO real:
  se inserta una factura AUTHORIZED de fixture directamente, igual que
  ``test_billing_credit_note.py::_insert_fixture_authorized_invoice``, y se
  invoca ``_apply_authorization_result`` a traves del ciclo real del
  simulador cuando MinIO esta disponible).
- ``workers/receivables.py::handle_invoice_authorized`` crea EXACTAMENTE un
  ``Receivable`` con su cuota de contado (total, due_date = issue_date) y es
  idempotente ante doble entrega del evento (mismo ``event_id`` via
  ``consume_once``, y tambien ante dos invocaciones directas del handler con
  ``event_id`` distintos, gracias al ``UniqueConstraint`` +verificacion
  explicita sobre ``sales_document_id``).
- ``GET /receivables``/``GET /receivables/{id}`` filtran por tenant.
"""

import socket
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.billing import SalesDocument, SalesDocumentInstallment, SalesDocumentLine
from app.models.receivables import Receivable, ReceivableInstallment
from app.workers.outbox import OutboxMessage, claim_outbox_batch
from app.workers.receivables import CONSUMER_NAME, handle_invoice_authorized
from app.workers.sri_transmission import INVOICE_AUTHORIZED_EVENT
from tests.test_billing_api import (
    TENANT_A,
    TENANT_B,
    _invoice_payload,
    _setup_billing_masters,
    auth,
    token_for,
)


def _minio_is_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 9000), timeout=1):
            return True
    except OSError:
        return False


async def _insert_authorized_invoice(
    *,
    tenant_id: uuid.UUID,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    party_id: uuid.UUID,
    product_id: uuid.UUID,
    sequential: str,
    total: Decimal,
    issue_date: date,
) -> SalesDocument:
    """Inserta una factura AUTHORIZED directamente (sin MinIO/firma real).

    Mismo patron que ``test_billing_credit_note.py`` para probar el handler
    de eventos sin depender de infraestructura externa: el handler nunca lee
    XML/artefactos, solo el ``SalesDocument`` ya persistido.
    """

    async with SessionFactory() as session, session.begin():
        document = SalesDocument(
            tenant_id=tenant_id,
            document_type="INVOICE",
            establishment_id=establishment_id,
            emission_point_id=emission_point_id,
            sequential=sequential,
            access_key=f"{sequential}".rjust(49, "1"),
            party_id=party_id,
            issue_date=issue_date,
            status="AUTHORIZED",
            currency="USD",
            subtotal=(total / Decimal("1.15")).quantize(Decimal("0.01")),
            tax_total=total - (total / Decimal("1.15")).quantize(Decimal("0.01")),
            total=total,
            fiscal_policy_version="ec-iva-v1",
            authorization_number=f"{sequential}".rjust(49, "1"),
        )
        session.add(document)
        await session.flush()
        session.add(
            SalesDocumentLine(
                tenant_id=tenant_id,
                sales_document_id=document.id,
                line_number=1,
                product_id=product_id,
                description="Fixture receivable",
                quantity=Decimal("1"),
                unit_price=total,
                discount=Decimal("0.00"),
                base_amount=document.subtotal,
                tax_sri_code="4",
                tax_rate=Decimal("15.000000"),
                tax_amount=document.tax_total,
            )
        )
        return document


async def _insert_authorized_invoice_with_installments(
    *,
    tenant_id: uuid.UUID,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    party_id: uuid.UUID,
    product_id: uuid.UUID,
    sequential: str,
    issue_date: date,
    installment_amounts: list[Decimal],
    installment_due_dates: list[date],
) -> SalesDocument:
    """Como ``_insert_authorized_invoice`` pero con ``SalesDocumentInstallment`` reales.

    Sprint 3 Fase 2: simula lo que ``services/billing.py::create_invoice_draft``
    persiste cuando ``InvoiceInput.installments`` declara mas de una cuota,
    para probar que ``handle_invoice_authorized`` materializa EXACTAMENTE esas
    cuotas (no la cuota unica de contado del fallback).
    """

    total = sum(installment_amounts, Decimal("0.00"))
    async with SessionFactory() as session, session.begin():
        document = SalesDocument(
            tenant_id=tenant_id,
            document_type="INVOICE",
            establishment_id=establishment_id,
            emission_point_id=emission_point_id,
            sequential=sequential,
            access_key=f"{sequential}".rjust(49, "1"),
            party_id=party_id,
            issue_date=issue_date,
            status="AUTHORIZED",
            currency="USD",
            subtotal=(total / Decimal("1.15")).quantize(Decimal("0.01")),
            tax_total=total - (total / Decimal("1.15")).quantize(Decimal("0.01")),
            total=total,
            fiscal_policy_version="ec-iva-v1",
            authorization_number=f"{sequential}".rjust(49, "1"),
        )
        session.add(document)
        await session.flush()
        session.add(
            SalesDocumentLine(
                tenant_id=tenant_id,
                sales_document_id=document.id,
                line_number=1,
                product_id=product_id,
                description="Fixture receivable multi-cuota",
                quantity=Decimal("1"),
                unit_price=total,
                discount=Decimal("0.00"),
                base_amount=document.subtotal,
                tax_sri_code="4",
                tax_rate=Decimal("15.000000"),
                tax_amount=document.tax_total,
            )
        )
        for sequence, (amount, due_date) in enumerate(
            zip(installment_amounts, installment_due_dates, strict=True), start=1
        ):
            session.add(
                SalesDocumentInstallment(
                    tenant_id=tenant_id,
                    sales_document_id=document.id,
                    sequence=sequence,
                    due_date=due_date,
                    amount=amount,
                )
            )
        return document


def _message_for(document: SalesDocument, *, event_id: uuid.UUID | None = None) -> OutboxMessage:
    return OutboxMessage(
        event_id=event_id or uuid.uuid4(),
        tenant_id=document.tenant_id,
        event_type=INVOICE_AUTHORIZED_EVENT,
        aggregate_type="sales_document",
        aggregate_id=str(document.id),
        payload={
            "sales_document_id": str(document.id),
            "tenant_id": str(document.tenant_id),
            "access_key": document.access_key,
        },
        correlation_id=str(uuid.uuid4()),
        attempts=1,
    )


async def test_handle_invoice_authorized_creates_one_receivable_with_cash_installment(
    client,
) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-happy")

    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000901",
        total=Decimal("115.00"),
        issue_date=date(2026, 7, 4),
    )

    message = _message_for(document)
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, message)
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(
                Receivable.tenant_id == TENANT_A,
                Receivable.sales_document_id == document.id,
            )
        )
        assert receivable is not None
        assert receivable.original_amount == Decimal("115.00")
        assert receivable.party_id == uuid.UUID(masters["party_id"])
        assert receivable.status == "OPEN"

        installments = list(
            (
                await session.scalars(
                    select(ReceivableInstallment).where(
                        ReceivableInstallment.receivable_id == receivable.id
                    )
                )
            ).all()
        )
        assert len(installments) == 1
        assert installments[0].amount == Decimal("115.00")
        assert installments[0].due_date == date(2026, 7, 4)

        receivable_count = await session.scalar(
            select(func.count())
            .select_from(Receivable)
            .where(Receivable.sales_document_id == document.id)
        )
        assert receivable_count == 1


async def test_handle_invoice_authorized_is_idempotent_on_duplicate_delivery(client) -> None:
    """Dos entregas del mismo evento (mismo event_id, via consume_once) -> un solo Receivable."""

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-idem")
    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000902",
        total=Decimal("230.00"),
        issue_date=date(2026, 7, 4),
    )

    from app.workers.outbox import consume_once

    message = _message_for(document)
    first = await consume_once(
        consumer_name=CONSUMER_NAME, message=message, handler=handle_invoice_authorized
    )
    second = await consume_once(
        consumer_name=CONSUMER_NAME, message=message, handler=handle_invoice_authorized
    )
    assert first is True
    assert second is False  # deduplicated by InboxEvent(consumer_name, event_id)

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Receivable)
            .where(Receivable.sales_document_id == document.id)
        )
        assert count == 1


async def test_handle_invoice_authorized_is_idempotent_across_distinct_event_ids(client) -> None:
    """Defensa en profundidad: dos event_id DISTINTOS para la misma factura -> un solo Receivable.

    Simula una re-publicacion (bug, o reintento manual) que produce un nuevo
    OutboxEvent con id propio para el mismo sales_document_id: la
    verificacion explicita en el handler (no solo el InboxEvent dedupe) debe
    seguir protegiendo la unicidad.
    """

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-double-event")
    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000903",
        total=Decimal("57.50"),
        issue_date=date(2026, 7, 4),
    )

    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document, event_id=uuid.uuid4()))
        await session.commit()
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document, event_id=uuid.uuid4()))
        await session.commit()

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Receivable)
            .where(Receivable.sales_document_id == document.id)
        )
        assert count == 1


async def test_handle_invoice_authorized_ignores_credit_notes(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-cn")
    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000904",
        total=Decimal("10.00"),
        issue_date=date(2026, 7, 4),
    )
    document.document_type = "CREDIT_NOTE"
    async with SessionFactory() as session, session.begin():
        await session.merge(document)

    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Receivable)
            .where(Receivable.sales_document_id == document.id)
        )
        assert count == 0


pytestmark_minio = pytest.mark.skipif(
    not _minio_is_reachable(),
    reason="MinIO is not reachable at localhost:9000 in this environment",
)


@pytestmark_minio
async def test_full_cycle_issue_and_authorize_publishes_invoice_authorized_event(client) -> None:
    """Ciclo real: emitir factura -> autorizar via simulador -> invoice.authorized en outbox."""

    from app.integrations.sri.simulator import SimulatorSRIClient, get_store
    from app.workers.sri_transmission import handle_invoice_signed

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-e2e")
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "rcv-e2e-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    issue_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/issue",
        headers=auth(token_invoices, "rcv-e2e-issue-0001"),
    )
    assert issue_response.status_code == 202, issue_response.text

    async with SessionFactory() as session, session.begin():
        messages = await claim_outbox_batch(session)
    matching = [
        message
        for message in messages
        if message.event_type == "invoice.signed" and message.aggregate_id == invoice_id
    ]
    assert len(matching) == 1
    signed_message = matching[0]

    get_store().reset()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, signed_message, sri_client=SimulatorSRIClient())
        await session.commit()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, signed_message, sri_client=SimulatorSRIClient())
        await session.commit()

    final = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token_invoices))
    assert final.json()["status"] == "AUTHORIZED", final.text

    async with SessionFactory() as session, session.begin():
        pending = await claim_outbox_batch(session)
    authorized_events = [
        message
        for message in pending
        if message.event_type == INVOICE_AUTHORIZED_EVENT and message.aggregate_id == invoice_id
    ]
    assert len(authorized_events) == 1

    async with SessionFactory() as session:
        await handle_invoice_authorized(session, authorized_events[0])
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == uuid.UUID(invoice_id))
        )
        assert receivable is not None
        assert receivable.original_amount == Decimal(final.json()["total"])


async def test_get_receivables_is_tenant_isolated(client) -> None:
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_a = await _setup_billing_masters(client, token_a, key_prefix="rcv-list-a")
    document_a = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters_a["establishment_id"]),
        emission_point_id=uuid.UUID(masters_a["emission_point_id"]),
        party_id=uuid.UUID(masters_a["party_id"]),
        product_id=uuid.UUID(masters_a["product_id"]),
        sequential="000000910",
        total=Decimal("42.00"),
        issue_date=date(2026, 7, 4),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document_a))
        await session.commit()

    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_b = await _setup_billing_masters(client, token_b, key_prefix="rcv-list-b")
    document_b = await _insert_authorized_invoice(
        tenant_id=TENANT_B,
        establishment_id=uuid.UUID(masters_b["establishment_id"]),
        emission_point_id=uuid.UUID(masters_b["emission_point_id"]),
        party_id=uuid.UUID(masters_b["party_id"]),
        product_id=uuid.UUID(masters_b["product_id"]),
        sequential="000000911",
        total=Decimal("99.00"),
        issue_date=date(2026, 7, 4),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document_b))
        await session.commit()

    token_a_read = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    listed = await client.get("/api/v1/receivables", headers=auth(token_a_read))
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}

    async with SessionFactory() as session:
        receivable_a = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document_a.id)
        )
        receivable_b = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document_b.id)
        )
    assert str(receivable_a.id) in ids
    assert str(receivable_b.id) not in ids

    # GET /receivables/{id} of another tenant's receivable must 404, not leak data.
    forbidden = await client.get(
        f"/api/v1/receivables/{receivable_b.id}", headers=auth(token_a_read)
    )
    assert forbidden.status_code == 404


async def test_get_receivables_requires_read_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])
    response = await client.get("/api/v1/receivables", headers=auth(token))
    assert response.status_code == 403


async def test_get_receivable_by_id_returns_account_item_shape(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-shape")
    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000920",
        total=Decimal("81.25"),
        issue_date=date(2026, 6, 1),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document.id)
        )

    token_read = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.get(
        f"/api/v1/receivables/{receivable.id}", headers=auth(token_read)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(receivable.id)
    assert body["partyId"] == masters["party_id"]
    assert body["originalAmount"] == "81.25"
    assert body["openAmount"] == "81.25"
    assert body["currency"] == "USD"
    # 2026-06-01 due date is in the past relative to any fiscal "today" in
    # this sprint's test window, so the account item surfaces as OVERDUE.
    assert body["status"] == "OVERDUE"
    assert body["dueDate"] == "2026-06-01"


async def test_handle_invoice_authorized_materializes_two_real_installments(client) -> None:
    """Sprint 3 Fase 2: 2 ``SalesDocumentInstallment`` reales -> 2 ``ReceivableInstallment``.

    Antes de esta fase el handler siempre colapsaba a una cuota de contado
    por el total; ahora debe leer las cuotas persistidas por
    ``services/billing.py::create_invoice_draft`` y materializarlas tal cual
    (misma fecha, mismo monto), sin caer al fallback.
    """

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-multi")

    document = await _insert_authorized_invoice_with_installments(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000930",
        issue_date=date(2026, 7, 4),
        installment_amounts=[Decimal("60.00"), Decimal("55.00")],
        installment_due_dates=[date(2026, 8, 4), date(2026, 9, 4)],
    )

    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document.id)
        )
        assert receivable is not None
        assert receivable.original_amount == Decimal("115.00")

        installments = list(
            (
                await session.scalars(
                    select(ReceivableInstallment)
                    .where(ReceivableInstallment.receivable_id == receivable.id)
                    .order_by(ReceivableInstallment.sequence)
                )
            ).all()
        )
        assert len(installments) == 2
        assert installments[0].amount == Decimal("60.00")
        assert installments[0].due_date == date(2026, 8, 4)
        assert installments[1].amount == Decimal("55.00")
        assert installments[1].due_date == date(2026, 9, 4)


async def test_handle_invoice_authorized_falls_back_to_single_installment_without_persisted_plan(
    client,
) -> None:
    """Sin ``SalesDocumentInstallment`` persistidas, cae a la cuota unica de contado.

    Cubre datos de una fase anterior (o migrados) sin plan de pago
    persistido: ``_insert_authorized_invoice`` (sin instalments) nunca crea
    filas en ``sales_document_installments``.
    """

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="rcv-fallback")
    document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000931",
        total=Decimal("77.00"),
        issue_date=date(2026, 7, 4),
    )

    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document.id)
        )
        installments = list(
            (
                await session.scalars(
                    select(ReceivableInstallment).where(
                        ReceivableInstallment.receivable_id == receivable.id
                    )
                )
            ).all()
        )
        assert len(installments) == 1
        assert installments[0].amount == Decimal("77.00")
        assert installments[0].due_date == date(2026, 7, 4)

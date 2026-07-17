"""Integracion HTTP de Receivables Fase 2 (E5-03/E5-04/E5-08).

Cubre ``POST /receivables/{id}/payments`` (cobro parcial, retenciones,
descuentos, idempotencia, sobreaplicacion), ``GET /receivables/{id}/movements``
(historial), concurrencia real contra PostgreSQL (dos cobros simultaneos nunca
sobreaplican), y el ciclo NC AUTHORIZED -> ``credit_note.authorized`` ->
aplicacion contra la cartera de la factura relacionada, incluyendo
idempotencia del propio evento.
"""

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory, engine
from app.models.receivables import CustomerCredit, Movement, Receivable
from app.workers.receivables import handle_credit_note_authorized, handle_invoice_authorized
from app.workers.sri_transmission import CREDIT_NOTE_AUTHORIZED_EVENT
from tests.test_billing_api import TENANT_A, _setup_billing_masters, auth, token_for
from tests.test_receivables_flow import _insert_authorized_invoice, _message_for


async def _create_receivable_via_event(
    *, key_prefix: str, sequential: str, total: Decimal, issue_date: date = date(2026, 12, 1)
) -> tuple[str, dict[str, str]]:
    """Crea masters + factura AUTHORIZED de fixture + Receivable via el handler real."""

    async def _run(client) -> tuple[str, dict[str, str]]:
        token = await token_for(
            client,
            "a@iaerp.local",
            TENANT_A,
            ["organization:write", "organization:read", "parties:write", "products:write"],
        )
        masters = await _setup_billing_masters(client, token, key_prefix=key_prefix)
        document = await _insert_authorized_invoice(
            tenant_id=TENANT_A,
            establishment_id=uuid.UUID(masters["establishment_id"]),
            emission_point_id=uuid.UUID(masters["emission_point_id"]),
            party_id=uuid.UUID(masters["party_id"]),
            product_id=uuid.UUID(masters["product_id"]),
            sequential=sequential,
            total=total,
            issue_date=issue_date,
        )
        async with SessionFactory() as session:
            await handle_invoice_authorized(session, _message_for(document))
            await session.commit()
        async with SessionFactory() as session:
            receivable = await session.scalar(
                select(Receivable).where(Receivable.sales_document_id == document.id)
            )
        return str(receivable.id), masters

    return _run


async def test_record_payment_partial_via_api_updates_open_amount(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-pay1", sequential="000000940", total=Decimal("100.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "pay-api-0001-0001"),
        json={
            "cashAmount": "40.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["openAmount"] == "60.00"
    assert body["status"] == "PARTIAL"


async def test_record_payment_idempotency_key_replay_does_not_duplicate_movement(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-pay2", sequential="000000941", total=Decimal("80.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    payload = {
        "cashAmount": "30.00",
        "paymentDate": "2026-07-10",
        "retentions": [],
        "discounts": [],
    }
    first = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "pay-idem-0001-0001"),
        json=payload,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "pay-idem-0001-0001"),
        json=payload,
    )
    assert second.status_code == 201, second.text
    assert first.json() == second.json()

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(
                        Movement.receivable_id == uuid.UUID(receivable_id),
                        Movement.movement_type == "PAYMENT",
                    )
                )
            ).all()
        )
    assert len(movements) == 1


async def test_record_payment_overapplication_returns_422_via_api(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-pay3", sequential="000000942", total=Decimal("50.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "pay-over-api-0001-0001"),
        json={
            "cashAmount": "50.01",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    assert response.status_code == 422, response.text


async def test_record_payment_requires_write_scope(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-pay4", sequential="000000943", total=Decimal("10.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "pay-scope-api-0001-0001"),
        json={
            "cashAmount": "5.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    assert response.status_code == 403


async def test_get_receivable_movements_lists_history(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-mov1", sequential="000000944", total=Decimal("90.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "mov-pay-0001-00001"),
        json={
            "cashAmount": "20.00",
            "paymentDate": "2026-07-10",
            "retentions": [
                {"kind": "RETENTION_IVA", "amount": "5.00", "reason": "Retencion IVA 5%"}
            ],
            "discounts": [],
        },
    )

    response = await client.get(
        f"/api/v1/receivables/{receivable_id}/movements", headers=auth(token)
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    types = sorted(row["movementType"] for row in rows)
    assert types == ["PAYMENT", "RETENTION"]


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row locks are required for this concurrency test",
)
async def test_concurrent_payments_never_overapply_the_same_receivable(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="api-conc1", sequential="000000945", total=Decimal("100.00")
    )
    receivable_id, _masters = await setup(client)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])

    async def pay(index: int):
        return await client.post(
            f"/api/v1/receivables/{receivable_id}/payments",
            headers=auth(token, f"pay-concurrent-{index:04d}"),
            json={
                "cashAmount": "60.00",
                "paymentDate": "2026-07-10",
                "retentions": [],
                "discounts": [],
            },
        )

    responses = await asyncio.gather(*(pay(i) for i in range(1, 3)))
    statuses = sorted(response.status_code for response in responses)
    # Exactly one of the two concurrent 60.00 payments fits in the 100.00
    # balance; the other must be rejected with 422 (never both accepted).
    assert statuses == [201, 422]

    async with SessionFactory() as session:
        entity = await session.get(Receivable, uuid.UUID(receivable_id))
        from app.services.receivables import compute_receivable_balance

        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
    assert balance == Decimal("40.00")


async def _authorize_credit_note_via_fixture(
    *,
    client,
    invoice_document,
    masters: dict[str, str],
    credit_note_total: Decimal,
    key_prefix: str,
) -> str:
    """Inserta una NC AUTHORIZED de fixture relacionada a ``invoice_document``.

    Devuelve ``(access_key, credit_note_id)``.
    """

    from app.models.billing import DocumentRelation, SalesDocument, SalesDocumentLine

    sequential = f"{hash(key_prefix) % 900000000:09d}"
    access_key = sequential.rjust(49, "3")
    async with SessionFactory() as session, session.begin():
        credit_note = SalesDocument(
            tenant_id=TENANT_A,
            document_type="CREDIT_NOTE",
            establishment_id=invoice_document.establishment_id,
            emission_point_id=invoice_document.emission_point_id,
            sequential=sequential,
            access_key=access_key,
            party_id=invoice_document.party_id,
            issue_date=date(2026, 7, 4),
            status="AUTHORIZED",
            currency="USD",
            subtotal=credit_note_total,
            tax_total=Decimal("0.00"),
            total=credit_note_total,
            fiscal_policy_version="ec-iva-v1",
            reason="Devolucion de mercaderia",
            authorization_number=access_key,
        )
        session.add(credit_note)
        await session.flush()
        session.add(
            SalesDocumentLine(
                tenant_id=TENANT_A,
                sales_document_id=credit_note.id,
                line_number=1,
                product_id=uuid.UUID(masters["product_id"]),
                description="Devolucion",
                quantity=Decimal("1"),
                unit_price=credit_note_total,
                discount=Decimal("0.00"),
                base_amount=credit_note_total,
                tax_sri_code="4",
                tax_rate=Decimal("0.000000"),
                tax_amount=Decimal("0.00"),
            )
        )
        session.add(
            DocumentRelation(
                tenant_id=TENANT_A,
                credit_note_id=credit_note.id,
                related_invoice_id=invoice_document.id,
            )
        )
    return access_key, credit_note.id


async def test_credit_note_authorized_event_applies_against_receivable(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="api-cn1")
    invoice_document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000950",
        total=Decimal("100.00"),
        issue_date=date(2026, 7, 4),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(invoice_document))
        await session.commit()

    access_key, credit_note_id = await _authorize_credit_note_via_fixture(
        client=client,
        invoice_document=invoice_document,
        masters=masters,
        credit_note_total=Decimal("35.00"),
        key_prefix="api-cn1",
    )

    from app.workers.outbox import OutboxMessage

    message = OutboxMessage(
        event_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        event_type=CREDIT_NOTE_AUTHORIZED_EVENT,
        aggregate_type="sales_document",
        aggregate_id=str(credit_note_id),
        payload={
            "sales_document_id": str(credit_note_id),
            "tenant_id": str(TENANT_A),
            "access_key": access_key,
        },
        correlation_id=str(uuid.uuid4()),
        attempts=1,
    )
    async with SessionFactory() as session:
        await handle_credit_note_authorized(session, message)
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == invoice_document.id)
        )
        from app.services.receivables import compute_receivable_balance

        balance = await compute_receivable_balance(
            session, tenant_id=TENANT_A, receivable=receivable
        )
    assert balance == Decimal("65.00")

    token_read = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.get(
        f"/api/v1/receivables/{receivable.id}", headers=auth(token_read)
    )
    assert response.json()["openAmount"] == "65.00"


async def test_credit_note_authorized_event_surplus_creates_customer_credit(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="api-cn2")
    invoice_document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000951",
        total=Decimal("30.00"),
        issue_date=date(2026, 7, 4),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(invoice_document))
        await session.commit()

    access_key, credit_note_id = await _authorize_credit_note_via_fixture(
        client=client,
        invoice_document=invoice_document,
        masters=masters,
        credit_note_total=Decimal("50.00"),
        key_prefix="api-cn2",
    )

    from app.workers.outbox import OutboxMessage

    message = OutboxMessage(
        event_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        event_type=CREDIT_NOTE_AUTHORIZED_EVENT,
        aggregate_type="sales_document",
        aggregate_id=str(credit_note_id),
        payload={
            "sales_document_id": str(credit_note_id),
            "tenant_id": str(TENANT_A),
            "access_key": access_key,
        },
        correlation_id=str(uuid.uuid4()),
        attempts=1,
    )
    async with SessionFactory() as session:
        await handle_credit_note_authorized(session, message)
        await session.commit()

    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == invoice_document.id)
        )
        credit = await session.scalar(
            select(CustomerCredit).where(CustomerCredit.origin_credit_note_id == credit_note_id)
        )
        from app.services.receivables import compute_receivable_balance

        balance = await compute_receivable_balance(
            session, tenant_id=TENANT_A, receivable=receivable
        )
    assert balance == Decimal("0.00")
    assert credit is not None
    assert credit.amount == Decimal("20.00")


async def test_credit_note_authorized_event_is_idempotent_on_retry(client) -> None:
    """Reentrega del evento (mismo access_key) nunca aplica la NC dos veces."""

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="api-cn3")
    invoice_document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000952",
        total=Decimal("40.00"),
        issue_date=date(2026, 7, 4),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(invoice_document))
        await session.commit()

    access_key, credit_note_id = await _authorize_credit_note_via_fixture(
        client=client,
        invoice_document=invoice_document,
        masters=masters,
        credit_note_total=Decimal("15.00"),
        key_prefix="api-cn3",
    )

    from app.workers.outbox import OutboxMessage

    def _message(event_id: uuid.UUID) -> OutboxMessage:
        return OutboxMessage(
            event_id=event_id,
            tenant_id=TENANT_A,
            event_type=CREDIT_NOTE_AUTHORIZED_EVENT,
            aggregate_type="sales_document",
            aggregate_id=str(credit_note_id),
            payload={
                "sales_document_id": str(credit_note_id),
                "tenant_id": str(TENANT_A),
                "access_key": access_key,
            },
            correlation_id=str(uuid.uuid4()),
            attempts=1,
        )

    async with SessionFactory() as session:
        await handle_credit_note_authorized(session, _message(uuid.uuid4()))
        await session.commit()
    async with SessionFactory() as session:
        await handle_credit_note_authorized(session, _message(uuid.uuid4()))
        await session.commit()

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(
                        Movement.movement_type == "CREDIT_NOTE",
                        Movement.support_reference == access_key,
                    )
                )
            ).all()
        )
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == invoice_document.id)
        )
        from app.services.receivables import compute_receivable_balance

        balance = await compute_receivable_balance(
            session, tenant_id=TENANT_A, receivable=receivable
        )
    assert len(movements) == 1
    assert balance == Decimal("25.00")

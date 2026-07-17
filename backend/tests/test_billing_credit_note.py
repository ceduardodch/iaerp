"""Fase 5 (E4-07): nota de credito con limite acreditable y tarifa historica.

Cubre:

- Validacion de la factura de sustento: debe existir, ser del mismo tenant,
  tipo INVOICE y estado AUTHORIZED (404/422 en los casos negativos).
- Control de saldo acreditable: la suma de NC AUTHORIZED/en curso relacionadas
  nunca supera el ``importeTotal`` de la factura (limite exacto permitido,
  exceso rechazado con 422).
- Vector 7 del ADR 0008: una NC sobre un sustento anterior a 2024-04-01 usa la
  tarifa/``codigoPorcentaje`` congelada en la linea de la factura (12%,
  ``ec-iva-v0``), nunca la vigente a la fecha de la NC.
- Integracion del ciclo completo: factura AUTHORIZED de fixture -> NC ->
  issue -> worker con el simulador SRI -> NC AUTHORIZED.
"""

import socket
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.billing import DocumentRelation, SalesDocument, SalesDocumentLine
from app.models.masters import TaxCategory
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


_MINIO_AVAILABLE = _minio_is_reachable()


async def _authorize_invoice(client, key_prefix: str) -> tuple[str, str]:
    """Crea una factura, la emite y la lleva a AUTHORIZED con el simulador real.

    Requiere MinIO real (igual que ``test_invoice_issue_flow.py``); se omite
    automaticamente si no esta disponible en este entorno.
    """

    from app.integrations.sri.simulator import SimulatorSRIClient, get_store
    from app.workers.outbox import claim_outbox_batch
    from app.workers.sri_transmission import handle_invoice_signed

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix=key_prefix)
    token_invoices = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["invoices:write", "invoices:read", "invoices:issue", "credit-notes:issue"],
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, f"{key_prefix}-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    issue_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/issue",
        headers=auth(token_invoices, f"{key_prefix}-issue-0001"),
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
    message = matching[0]

    get_store().reset()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    final = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token_invoices))
    assert final.json()["status"] == "AUTHORIZED", final.text
    return invoice_id, token_invoices


async def _insert_fixture_authorized_invoice(
    *,
    tenant_id: uuid.UUID,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    party_id: uuid.UUID,
    product_id: uuid.UUID,
    issue_date: date,
    tax_sri_code: str,
    tax_rate: Decimal,
    quantity: Decimal,
    unit_price: Decimal,
) -> SalesDocument:
    """Inserta directamente una factura AUTHORIZED historica (fixture de dataset).

    Usado solo para el vector 7 (sustento 2024-03-15, tarifa 12% historica):
    ``POST /invoices`` rechaza ``issueDate`` en el pasado no por regla de
    negocio sino porque nunca hay un caso real de emitir HOY una factura con
    fecha pasada; el dataset sprint-02-v1 sí necesita ese documento historico
    ya AUTHORIZED para poder emitir una NC sobre el en 2026, exactamente como
    describe ``docs/sprints/sprint-02.md`` ("plan de pruebas y datos").
    """

    async with SessionFactory() as session, session.begin():
        base = Decimal(quantity) * Decimal(unit_price)
        base_amount = base.quantize(Decimal("0.01"))
        tax_amount = (base_amount * tax_rate / Decimal(100)).quantize(Decimal("0.01"))
        document = SalesDocument(
            tenant_id=tenant_id,
            document_type="INVOICE",
            establishment_id=establishment_id,
            emission_point_id=emission_point_id,
            sequential="000000900",
            access_key="1" * 49,
            party_id=party_id,
            issue_date=issue_date,
            status="AUTHORIZED",
            currency="USD",
            subtotal=base_amount,
            tax_total=tax_amount,
            total=base_amount + tax_amount,
            fiscal_policy_version="ec-iva-v0",
            authorization_number="1" * 49,
        )
        session.add(document)
        await session.flush()
        session.add(
            SalesDocumentLine(
                tenant_id=tenant_id,
                sales_document_id=document.id,
                line_number=1,
                product_id=product_id,
                description="Fixture historica",
                quantity=quantity,
                unit_price=unit_price,
                discount=Decimal("0.00"),
                base_amount=base_amount,
                tax_sri_code=tax_sri_code,
                tax_rate=tax_rate,
                tax_amount=tax_amount,
            )
        )
        return document


def _credit_note_payload(invoice_id: str, product_id: str, **overrides) -> dict:
    payload = {
        "invoiceId": invoice_id,
        "reason": "Devolucion parcial de mercaderia",
        "lines": [
            {
                "productId": product_id,
                "description": "Devolucion consultoria",
                "quantity": "1",
                "unitPrice": "50.000000",
                "discount": "0.00",
                "taxCode": "4",
            }
        ],
    }
    payload.update(overrides)
    return payload


pytestmark = pytest.mark.skipif(
    not _MINIO_AVAILABLE,
    reason="MinIO is not reachable at localhost:9000 in this environment",
)


async def test_credit_note_rejects_invoice_from_another_tenant(client) -> None:
    invoice_id, _token_a = await _authorize_invoice(client, "cn-cross-tenant")

    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_b = await _setup_billing_masters(client, token_b, key_prefix="cn-cross-tenant-b")
    token_b_cn = await token_for(client, "b@iaerp.local", TENANT_B, ["credit-notes:issue"])

    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token_b_cn, "cn-cross-tenant-0001"),
        json=_credit_note_payload(invoice_id, masters_b["product_id"]),
    )
    assert response.status_code == 404, response.text


async def test_credit_note_rejects_invoice_not_authorized(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="cn-notauth")
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "credit-notes:issue"]
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "cn-notauth-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]  # still DRAFT: never issued

    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token_invoices, "cn-notauth-0001-key"),
        json=_credit_note_payload(invoice_id, masters["product_id"]),
    )
    assert response.status_code == 422, response.text
    assert "AUTHORIZED" in response.text


async def test_credit_note_at_exact_creditable_limit_is_allowed(client) -> None:
    invoice_id, token = await _authorize_invoice(client, "cn-exact-limit")
    invoice = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    invoice_body = invoice.json()
    product_id = invoice_body["lines"][0]["productId"]
    full_quantity = invoice_body["lines"][0]["quantity"]

    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-exact-limit-0001"),
        json=_credit_note_payload(
            invoice_id,
            product_id,
            lines=[
                {
                    "productId": product_id,
                    "description": "Devolucion total",
                    "quantity": full_quantity,
                    "unitPrice": "50.000000",
                    "discount": "0.00",
                    "taxCode": "4",
                }
            ],
        ),
    )
    assert response.status_code == 202, response.text

    async with SessionFactory() as session:
        relation = await session.scalar(
            select(DocumentRelation).where(
                DocumentRelation.tenant_id == TENANT_A,
                DocumentRelation.related_invoice_id == uuid.UUID(invoice_id),
            )
        )
        assert relation is not None
        credit_note = await session.get(SalesDocument, relation.credit_note_id)
        assert credit_note is not None
        assert credit_note.total == Decimal(invoice_body["total"])


async def test_credit_note_exceeding_creditable_balance_is_rejected(client) -> None:
    invoice_id, token = await _authorize_invoice(client, "cn-exceed")
    invoice = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    invoice_body = invoice.json()
    product_id = invoice_body["lines"][0]["productId"]
    full_quantity = invoice_body["lines"][0]["quantity"]

    over_response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-exceed-0001-key"),
        json=_credit_note_payload(
            invoice_id,
            product_id,
            lines=[
                {
                    "productId": product_id,
                    # La cantidad ya excede lo facturado en la linea original.
                    "description": "Devolucion excesiva",
                    "quantity": str(Decimal(full_quantity) + Decimal("1")),
                    "unitPrice": "50.000000",
                    "discount": "0.00",
                    "taxCode": "4",
                }
            ],
        ),
    )
    assert over_response.status_code == 422, over_response.text


async def test_credit_note_balance_is_reserved_by_a_prior_credit_note_in_progress(
    client,
) -> None:
    """Dos NC en secuencia sobre la misma factura no pueden sumar mas que el total."""

    invoice_id, token = await _authorize_invoice(client, "cn-reserve")
    invoice = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    invoice_body = invoice.json()
    product_id = invoice_body["lines"][0]["productId"]
    full_quantity = Decimal(invoice_body["lines"][0]["quantity"])

    # Primera NC: la mitad de la cantidad facturada.
    half_quantity = full_quantity / 2
    first = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-reserve-0001-key"),
        json=_credit_note_payload(
            invoice_id,
            product_id,
            lines=[
                {
                    "productId": product_id,
                    "description": "Primera devolucion parcial",
                    "quantity": str(half_quantity),
                    "unitPrice": "50.000000",
                    "discount": "0.00",
                    "taxCode": "4",
                }
            ],
        ),
    )
    assert first.status_code == 202, first.text

    # Segunda NC por la cantidad completa: aunque cada una individualmente
    # cabria dentro del total de la factura, la primera ya reservo saldo (aun
    # sin llegar a AUTHORIZED), asi que la segunda debe exceder el saldo
    # disponible.
    second = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-reserve-0002-key"),
        json=_credit_note_payload(
            invoice_id,
            product_id,
            lines=[
                {
                    "productId": product_id,
                    "description": "Segunda devolucion, deberia exceder saldo",
                    "quantity": str(full_quantity),
                    "unitPrice": "50.000000",
                    "discount": "0.00",
                    "taxCode": "4",
                }
            ],
        ),
    )
    assert second.status_code == 422, second.text


async def test_credit_note_line_must_reference_invoice_product(client) -> None:
    invoice_id, token = await _authorize_invoice(client, "cn-badproduct")
    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-badproduct-0001"),
        json=_credit_note_payload(invoice_id, str(uuid.uuid4())),
    )
    assert response.status_code == 422, response.text


async def test_full_credit_note_cycle_reaches_authorized(client) -> None:
    """Factura AUTHORIZED de fixture -> NC -> issue -> worker -> NC AUTHORIZED."""

    from app.integrations.sri.simulator import SimulatorSRIClient, get_store
    from app.workers.outbox import claim_outbox_batch
    from app.workers.sri_transmission import handle_invoice_signed

    invoice_id, token = await _authorize_invoice(client, "cn-full-cycle")
    invoice = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    invoice_body = invoice.json()
    product_id = invoice_body["lines"][0]["productId"]

    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token, "cn-full-cycle-0001"),
        json=_credit_note_payload(invoice_id, product_id),
    )
    assert response.status_code == 202, response.text

    async with SessionFactory() as session:
        relation = await session.scalar(
            select(DocumentRelation).where(
                DocumentRelation.tenant_id == TENANT_A,
                DocumentRelation.related_invoice_id == uuid.UUID(invoice_id),
            )
        )
        assert relation is not None
        credit_note_id = relation.credit_note_id

    credit_note_response = await client.get(
        f"/api/v1/invoices/{credit_note_id}", headers=auth(token)
    )
    assert credit_note_response.status_code == 200
    credit_note_body = credit_note_response.json()
    assert credit_note_body["type"] == "CREDIT_NOTE"
    assert credit_note_body["status"] == "SIGNED"
    assert credit_note_body["accessKey"] is not None

    async with SessionFactory() as session, session.begin():
        messages = await claim_outbox_batch(session)
    matching = [
        message
        for message in messages
        if message.event_type == "invoice.signed"
        and message.aggregate_id == str(credit_note_id)
    ]
    assert len(matching) == 1
    message = matching[0]

    get_store().reset()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    final = await client.get(f"/api/v1/invoices/{credit_note_id}", headers=auth(token))
    assert final.json()["status"] == "AUTHORIZED", final.text


async def test_credit_note_over_historical_invoice_uses_supporting_document_rate(
    client,
) -> None:
    """Vector 7 del ADR 0008: NC sobre sustento 2024-03-15 (12%) usa tarifa historica."""

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="cn-historical")
    token_cn = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:read", "credit-notes:issue"]
    )

    async with SessionFactory() as session, session.begin():
        session.add(
            TaxCategory(
                tenant_id=TENANT_A,
                sri_code="2",
                name="IVA 12% (historico)",
                rate=Decimal("12.000000"),
                valid_from=date(2012, 1, 1),
                valid_to=date(2024, 3, 31),
            )
        )

    invoice = await _insert_fixture_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        issue_date=date(2024, 3, 15),
        tax_sri_code="2",
        tax_rate=Decimal("12.000000"),
        quantity=Decimal("5"),
        unit_price=Decimal("20.00"),
    )
    assert invoice.total == Decimal("112.00")

    response = await client.post(
        "/api/v1/credit-notes",
        headers=auth(token_cn, "cn-historical-0001"),
        json={
            "invoiceId": str(invoice.id),
            "reason": "Devolucion parcial sobre sustento historico",
            "lines": [
                {
                    "productId": masters["product_id"],
                    "description": "Devolucion 2 unidades",
                    "quantity": "2",
                    "unitPrice": "20.00",
                    "discount": "0.00",
                    "taxCode": "2",
                }
            ],
        },
    )
    assert response.status_code == 202, response.text

    async with SessionFactory() as session:
        relation = await session.scalar(
            select(DocumentRelation).where(
                DocumentRelation.tenant_id == TENANT_A,
                DocumentRelation.related_invoice_id == invoice.id,
            )
        )
        assert relation is not None
        credit_note = await session.get(SalesDocument, relation.credit_note_id)
        assert credit_note is not None
        # Vector 7: tarifa 12% (no 15%), version historica ec-iva-v0.
        assert credit_note.fiscal_policy_version == "ec-iva-v0"
        assert credit_note.subtotal == Decimal("40.00")
        assert credit_note.tax_total == Decimal("4.80")
        assert credit_note.total == Decimal("44.80")

        lines = list(
            (
                await session.scalars(
                    select(SalesDocumentLine).where(
                        SalesDocumentLine.sales_document_id == credit_note.id
                    )
                )
            ).all()
        )
        assert len(lines) == 1
        assert lines[0].tax_sri_code == "2"
        assert lines[0].tax_rate == Decimal("12.000000")

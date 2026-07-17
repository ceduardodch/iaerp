import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory, engine
from app.models.billing import Sequence
from app.models.platform import AuditEvent, OutboxEvent

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


async def token_for(client, email: str, tenant_id: uuid.UUID, scopes=None) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": email,
            "tenantId": str(tenant_id),
            "scopes": scopes or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def _setup_billing_masters(client, token: str, *, key_prefix: str) -> dict[str, str]:
    """Crea establishment/emission-point/party/product usados por una factura."""

    establishment = await client.post(
        "/api/v1/establishments",
        headers=auth(token, f"{key_prefix}-establishment-key"),
        json={"code": "001", "name": "Matriz", "address": "Av. Siempre Viva 123"},
    )
    assert establishment.status_code == 201, establishment.text
    establishment_id = establishment.json()["id"]

    emission_point = await client.post(
        "/api/v1/emission-points",
        headers=auth(token, f"{key_prefix}-emission-point-key"),
        json={"establishmentId": establishment_id, "code": "001"},
    )
    assert emission_point.status_code == 201, emission_point.text
    emission_point_id = emission_point.json()["id"]

    party = await client.post(
        "/api/v1/parties",
        headers=auth(token, f"{key_prefix}-party-key-000"),
        json={
            "name": "Cliente Facturable",
            "identificationType": "CEDULA",
            "identificationNumber": "1790000001",
            "roles": ["CUSTOMER"],
        },
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]

    taxes = await client.get("/api/v1/tax-categories", headers=auth(token))
    tax_code = taxes.json()[0]["sriCode"]

    product = await client.post(
        "/api/v1/products",
        headers=auth(token, f"{key_prefix}-product-key-0"),
        json={
            "name": "Servicio de consultoria",
            "code": f"{key_prefix.upper()}-001",
            "unitPrice": "50.000000",
            "taxCategoryId": taxes.json()[0]["id"],
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    return {
        "establishment_id": establishment_id,
        "emission_point_id": emission_point_id,
        "party_id": party_id,
        "product_id": product_id,
        "tax_code": tax_code,
    }


def _invoice_payload(masters: dict[str, str], **overrides) -> dict:
    payload = {
        "customerId": masters["party_id"],
        "establishmentId": masters["establishment_id"],
        "emissionPointId": masters["emission_point_id"],
        "issueDate": "2026-07-04",
        "installments": [{"dueDate": "2026-08-04", "amount": "115.00"}],
        "lines": [
            {
                "productId": masters["product_id"],
                "description": "Consultoria julio",
                "quantity": "2",
                "unitPrice": "50.000000",
                "discount": "0.00",
                "taxCode": masters["tax_code"],
            }
        ],
    }
    payload.update(overrides)
    return payload


async def test_create_invoice_draft_recalculates_totals_ignoring_client_amounts(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="draft-a")

    token_invoices = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["invoices:write", "invoices:read"],
    )
    payload = _invoice_payload(masters)
    # El cliente intenta enviar totales falsos; deben ser ignorados porque el
    # schema de entrada ni siquiera acepta subtotal/tax/total en InvoiceInput.
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-draft-0001"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["type"] == "INVOICE"
    assert body["subtotal"] == "100.00"
    assert body["tax"] == "15.00"
    assert body["total"] == "115.00"
    assert body["sequential"] == "000000001"
    assert body["accessKey"] is None
    assert len(body["lines"]) == 1
    assert body["lines"][0]["baseAmount"] == "100.00"
    assert body["lines"][0]["taxAmount"] == "15.00"

    get_response = await client.get(
        f"/api/v1/invoices/{body['id']}",
        headers=auth(token_invoices),
    )
    assert get_response.status_code == 200
    assert get_response.json() == body


async def test_create_invoice_draft_ignores_client_supplied_totals(client):
    """``InvoiceInput`` no declara subtotal/tax/total: si el cliente los envia
    igual, Pydantic los descarta como campos desconocidos y el backend calcula
    el total real a partir de las lineas, sin verse afectado por el intento.
    """

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="draft-strict")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    payload = _invoice_payload(masters)
    payload["total"] = "999999.99"
    payload["subtotal"] = "999999.99"
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-draft-strict-0001"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    assert response.json()["total"] == "115.00"
    assert response.json()["subtotal"] == "100.00"


async def test_create_invoice_draft_persists_installments(client):
    """Sprint 3 Fase 2: ``installments`` persiste en ``sales_document_installments``.

    Antes de esta fase el campo se aceptaba y se descartaba; ahora
    ``services/billing.py::create_invoice_draft`` debe persistir cada cuota
    declarada, con la fecha y el monto exactos que envio el cliente.
    """

    from app.models.billing import SalesDocumentInstallment

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="draft-installments")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    payload = _invoice_payload(
        masters,
        installments=[
            {"dueDate": "2026-08-04", "amount": "60.00"},
            {"dueDate": "2026-09-04", "amount": "55.00"},
        ],
    )
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-draft-installments-0001"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]

    async with SessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(SalesDocumentInstallment)
                    .where(SalesDocumentInstallment.sales_document_id == uuid.UUID(document_id))
                    .order_by(SalesDocumentInstallment.sequence)
                )
            ).all()
        )
    assert len(rows) == 2
    assert rows[0].amount == Decimal("60.00")
    assert rows[0].due_date.isoformat() == "2026-08-04"
    assert rows[1].amount == Decimal("55.00")
    assert rows[1].due_date.isoformat() == "2026-09-04"


async def test_create_invoice_draft_without_installments_defaults_to_single_contado(client):
    """Sin plan de pago, el backend crea una sola cuota al contado = total.

    La UI nunca calcula el total, asi que emite sin declarar cuotas; el backend
    deriva una unica cuota por el total con vencimiento en la fecha de emision.
    """

    from app.models.billing import SalesDocumentInstallment

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="draft-no-installments")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    payload = _invoice_payload(masters, installments=[])
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-draft-no-installments-0001"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    document_id = body["id"]

    async with SessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(SalesDocumentInstallment).where(
                        SalesDocumentInstallment.sales_document_id == uuid.UUID(document_id)
                    )
                )
            ).all()
        )
    assert len(rows) == 1
    assert rows[0].amount == Decimal(body["total"])
    assert rows[0].due_date.isoformat() == "2026-07-04"


async def test_create_invoice_draft_rejects_installments_not_summing_to_total(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="draft-bad-installments")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    payload = _invoice_payload(
        masters,
        installments=[
            {"dueDate": "2026-08-04", "amount": "60.00"},
            {"dueDate": "2026-09-04", "amount": "54.00"},
        ],
    )
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-draft-bad-installments-0001"),
        json=payload,
    )
    assert response.status_code == 422, response.text


async def test_sequential_increments_per_establishment_and_emission_point(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="seq-a")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    first = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-seq-0001"),
        json=_invoice_payload(masters),
    )
    second = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-seq-0002"),
        json=_invoice_payload(masters),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["sequential"] == "000000001"
    assert second.json()["sequential"] == "000000002"


async def test_invoice_draft_is_tenant_isolated(client):
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_a = await _setup_billing_masters(client, token_a, key_prefix="tenant-a")
    token_a_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token_a_invoices, "invoice-tenant-a-0001"),
        json=_invoice_payload(masters_a),
    )
    assert created.status_code == 201

    token_b_invoices = await token_for(client, "b@iaerp.local", TENANT_B, ["invoices:read"])
    forbidden = await client.get(
        f"/api/v1/invoices/{created.json()['id']}",
        headers=auth(token_b_invoices),
    )
    assert forbidden.status_code == 404


async def test_invoice_draft_rejects_foreign_tenant_party(client):
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_a = await _setup_billing_masters(client, token_a, key_prefix="cross-a")

    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_b = await _setup_billing_masters(client, token_b, key_prefix="cross-b")

    token_b_invoices = await token_for(client, "b@iaerp.local", TENANT_B, ["invoices:write"])
    payload = _invoice_payload(masters_b, customerId=masters_a["party_id"])
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_b_invoices, "invoice-cross-tenant-0001"),
        json=payload,
    )
    assert response.status_code == 404


async def test_invoice_draft_idempotency_replay_returns_same_document(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="idem-a")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    headers = auth(token_invoices, "invoice-idempotent-0001")
    payload = _invoice_payload(masters)

    first = await client.post("/api/v1/invoices", headers=headers, json=payload)
    replay = await client.post("/api/v1/invoices", headers=headers, json=payload)
    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json() == replay.json()

    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == TENANT_A, AuditEvent.action == "invoice.draft_created"
                )
            )
        ) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == TENANT_A,
                    OutboxEvent.event_type == "invoice.draft_created",
                )
            )
        ) == 1

    # No second sequential is burned by the replay: a second, distinct draft
    # still gets 000000002 (not 000000003).
    second_payload = _invoice_payload(masters)
    second = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-idempotent-0002"),
        json=second_payload,
    )
    assert second.status_code == 201
    assert second.json()["sequential"] == "000000002"


async def test_list_invoices_is_tenant_isolated_and_capped(client):
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_a = await _setup_billing_masters(client, token_a, key_prefix="list-a")
    token_a_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token_a_invoices, "invoice-list-a-0001"),
        json=_invoice_payload(masters_a),
    )
    assert created.status_code == 201, created.text

    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters_b = await _setup_billing_masters(client, token_b, key_prefix="list-b")
    token_b_invoices = await token_for(client, "b@iaerp.local", TENANT_B, ["invoices:write"])
    created_b = await client.post(
        "/api/v1/invoices",
        headers=auth(token_b_invoices, "invoice-list-b-0001"),
        json=_invoice_payload(masters_b),
    )
    assert created_b.status_code == 201, created_b.text

    token_a_read = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    listed = await client.get("/api/v1/invoices", headers=auth(token_a_read))
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}
    assert created.json()["id"] in ids
    assert created_b.json()["id"] not in ids


async def test_list_invoices_filters_by_status_and_query(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="list-filter")
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "invoice-list-filter-0001"),
        json=_invoice_payload(masters),
    )
    assert created.status_code == 201, created.text
    sequential = created.json()["sequential"]

    by_status = await client.get(
        "/api/v1/invoices",
        params={"status": "DRAFT"},
        headers=auth(token_invoices),
    )
    assert by_status.status_code == 200
    assert all(row["status"] == "DRAFT" for row in by_status.json())
    assert created.json()["id"] in {row["id"] for row in by_status.json()}

    by_query = await client.get(
        "/api/v1/invoices",
        params={"q": sequential},
        headers=auth(token_invoices),
    )
    assert by_query.status_code == 200
    assert {row["id"] for row in by_query.json()} == {created.json()["id"]}

    by_authorized_status = await client.get(
        "/api/v1/invoices",
        params={"status": "AUTHORIZED"},
        headers=auth(token_invoices),
    )
    assert by_authorized_status.status_code == 200
    assert created.json()["id"] not in {row["id"] for row in by_authorized_status.json()}


async def test_list_invoices_requires_read_scope(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])
    response = await client.get("/api/v1/invoices", headers=auth(token))
    assert response.status_code == 403


async def test_invoice_draft_requires_write_scope(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "invoice-scope-0001"),
        json=_invoice_payload(
            {
                "party_id": str(uuid.uuid4()),
                "establishment_id": str(uuid.uuid4()),
                "emission_point_id": str(uuid.uuid4()),
                "product_id": str(uuid.uuid4()),
                "tax_code": "4",
            }
        ),
    )
    assert response.status_code == 403


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row locks are required for this concurrency test",
)
async def test_concurrent_tenant_writes_serialize_without_deadlock(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="concurrent-a")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    async def create_invoice(index: int):
        return await client.post(
            "/api/v1/invoices",
            headers=auth(token_invoices, f"invoice-concurrent-{index:04d}"),
            json=_invoice_payload(masters),
        )

    responses = await asyncio.gather(*(create_invoice(i) for i in range(1, 6)))
    assert [response.status_code for response in responses] == [201] * 5

    sequentials = sorted(response.json()["sequential"] for response in responses)
    assert sequentials == [f"{value:09d}" for value in range(1, 6)]

    async with SessionFactory() as session:
        sequence_row = await session.scalar(
            select(Sequence).where(
                Sequence.tenant_id == TENANT_A,
                Sequence.document_type == "INVOICE",
            )
        )
        assert sequence_row is not None
        assert sequence_row.next_value == 6

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory, engine
from app.models.billing import DocumentArtifact, SalesDocument, Sequence
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


async def test_establishment_address_cannot_change_while_invoice_is_in_sri(client):
    setup_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup_token, key_prefix="address-lock")
    invoice_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(invoice_token, "address-lock-invoice-create"),
        json=_invoice_payload(masters),
    )
    assert created.status_code == 201, created.text

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, uuid.UUID(created.json()["id"]))
        assert document is not None
        document.status = "SIGNED"
        await session.commit()

    blocked = await client.put(
        f"/api/v1/establishments/{masters['establishment_id']}",
        headers=auth(setup_token, "address-lock-update-blocked"),
        json={"name": "Matriz", "address": "Dirección B"},
    )
    assert blocked.status_code == 409
    assert "proceso con el SRI" in blocked.json()["detail"]

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, uuid.UUID(created.json()["id"]))
        assert document is not None
        document.status = "AUTHORIZED"
        await session.commit()

    updated = await client.put(
        f"/api/v1/establishments/{masters['establishment_id']}",
        headers=auth(setup_token, "address-lock-update-terminal"),
        json={"name": "Matriz", "address": "Dirección B"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["address"] == "Dirección B"


async def test_authorized_invoice_email_requires_confirmation_and_attaches_ride_and_xml(
    client, monkeypatch
):
    setup_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup_token, key_prefix="email-invoice")
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "email-invoice-create-0001"),
        json=_invoice_payload(masters),
    )
    assert created.status_code == 201, created.text
    document_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as session:
        document = await session.get(SalesDocument, document_id)
        assert document is not None
        document.status = "AUTHORIZED"
        session.add_all(
            [
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=document_id,
                    artifact_type="xml-signed",
                    object_key="private/invoice.xml",
                    sha256="a" * 64,
                    version=1,
                ),
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=document_id,
                    artifact_type="ride-pdf",
                    object_key="private/invoice.pdf",
                    sha256="b" * 64,
                    version=1,
                ),
            ]
        )
        await session.commit()

    sent: list[dict[str, object]] = []

    async def fake_download(*, object_key: str, bucket_name=None) -> bytes:
        del bucket_name
        return b"<xml/>" if object_key.endswith(".xml") else b"%PDF-1.4"

    async def fake_send(_session, _context, **kwargs) -> str:
        sent.append(kwargs)
        return "gmail-message-1"

    monkeypatch.setattr("app.services.billing.storage.download_artifact", fake_download)
    monkeypatch.setattr("app.services.billing.crm_integrations.send_google_email", fake_send)
    sender = await client.put(
        "/api/v1/organization/invoice-email-template",
        headers=auth(setup_token, "email-invoice-sender-0001"),
        json={
            "subject": "Factura {{numero_factura}} · {{empresa}}",
            "body": (
                "Hola {{cliente}}. Fecha límite de pago: {{vencimiento}}. "
                "Plazo acordado: {{plazo}}. Total: ${{total}}"
            ),
            "fromAddress": "contabilidad@b2b.com.ec",
            "fromName": "Contabilidad B2B",
        },
    )
    assert sender.status_code == 200, sender.text
    preview = await client.get(
        f"/api/v1/invoices/{document_id}/email-preview",
        headers=auth(token),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["dueDate"] == "2026-08-04"
    assert preview.json()["paymentTermsDays"] == 31
    assert preview.json()["senderAddress"] == "contabilidad@b2b.com.ec"
    assert preview.json()["senderName"] == "Contabilidad B2B"
    assert preview.json()["subject"] == "Factura 001-001-000000001 · Tenant A"
    assert "Fecha límite de pago: 2026-08-04" in preview.json()["message"]
    assert "Plazo acordado: 31 días" in preview.json()["message"]
    assert "Total: $115.00" in preview.json()["message"]
    assert preview.json()["attachmentNames"] == [
        "FACTURA-001-001-000000001.xml",
        "FACTURA-001-001-000000001.pdf",
    ]

    request_headers = auth(token, "email-invoice-send-0001")
    response = await client.post(
        f"/api/v1/invoices/{document_id}/email",
        headers=request_headers,
        json={"recipient": "facturas@cliente.example"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recipient"] == "facturas@cliente.example"
    assert response.json()["senderAddress"] == "contabilidad@b2b.com.ec"
    assert response.json()["senderName"] == "Contabilidad B2B"
    assert response.json()["attachmentNames"] == [
        "FACTURA-001-001-000000001.xml",
        "FACTURA-001-001-000000001.pdf",
    ]
    assert len(sent) == 1
    assert sent[0]["subject"] == preview.json()["subject"]
    assert sent[0]["message"] == preview.json()["message"]
    assert sent[0]["sender_address"] == "contabilidad@b2b.com.ec"
    assert sent[0]["sender_name"] == "Contabilidad B2B"
    assert sent[0]["reply_to"] == "contabilidad@b2b.com.ec"
    assert [item[1] for item in sent[0]["attachments"]] == [
        "application/xml",
        "application/pdf",
    ]

    replay = await client.post(
        f"/api/v1/invoices/{document_id}/email",
        headers=request_headers,
        json={"recipient": "facturas@cliente.example"},
    )
    assert replay.status_code == 200
    assert replay.json() == response.json()
    assert len(sent) == 1


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


@pytest.mark.parametrize("failed_status", ["REJECTED", "NOT_AUTHORIZED"])
async def test_archive_failed_invoice_hides_it_from_operational_listing(
    client, failed_status: str
):
    """Un rechazo se archiva con trazabilidad, no se elimina ni se confunde con autorizado."""

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(
        client, token, key_prefix=f"archive-{failed_status.lower()}"
    )
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, f"archive-{failed_status.lower()}-draft"),
        json=_invoice_payload(masters),
    )
    assert created.status_code == 201, created.text
    invoice_id = uuid.UUID(created.json()["id"])

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, invoice_id)
        assert document is not None
        document.status = failed_status
        await session.commit()

    archived = await client.post(
        f"/api/v1/invoices/{invoice_id}/archive",
        headers=auth(token_invoices, f"archive-{failed_status.lower()}-request"),
        json={"reason": "Prueba de emisión SRI; comprobante no autorizado."},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == failed_status

    listed = await client.get("/api/v1/invoices", headers=auth(token_invoices))
    assert listed.status_code == 200
    assert str(invoice_id) not in {item["id"] for item in listed.json()}

    # La consulta directa mantiene el registro disponible para fiscalización.
    detail = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token_invoices))
    assert detail.status_code == 200

    async with SessionFactory() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == TENANT_A,
                AuditEvent.entity_id == str(invoice_id),
                AuditEvent.action == "invoice.archived",
            )
        )
        assert audit is not None


async def test_archive_refuses_an_authorized_invoice(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="archive-authorized")
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    created = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "archive-authorized-draft"),
        json=_invoice_payload(masters),
    )
    assert created.status_code == 201, created.text
    invoice_id = uuid.UUID(created.json()["id"])

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, invoice_id)
        assert document is not None
        document.status = "AUTHORIZED"
        await session.commit()

    response = await client.post(
        f"/api/v1/invoices/{invoice_id}/archive",
        headers=auth(token_invoices, "archive-authorized-request"),
        json={"reason": "No debe ser posible."},
    )
    assert response.status_code == 409


async def test_duplicate_invoice_creates_a_new_draft_without_fiscal_artifacts(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="duplicate-invoice")
    token_invoices = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])
    original = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "duplicate-invoice-source"),
        json=_invoice_payload(
            masters,
            installments=[
                {"dueDate": "2026-08-04", "amount": "60.00"},
                {"dueDate": "2026-09-04", "amount": "55.00"},
            ],
        ),
    )
    assert original.status_code == 201, original.text

    duplicate = await client.post(
        f"/api/v1/invoices/{original.json()['id']}/duplicate",
        headers=auth(token_invoices, "duplicate-invoice-copy"),
    )
    assert duplicate.status_code == 201, duplicate.text
    copied = duplicate.json()
    assert copied["id"] != original.json()["id"]
    assert copied["status"] == "DRAFT"
    assert copied["sequential"] != original.json()["sequential"]
    assert copied["accessKey"] is None
    assert copied["total"] == original.json()["total"]
    assert len(copied["lines"]) == len(original.json()["lines"])
    assert copied["lines"][0]["description"] == original.json()["lines"][0]["description"]
    assert copied["lines"][0]["baseAmount"] == original.json()["lines"][0]["baseAmount"]
    source_issue_date = date.fromisoformat(original.json()["issueDate"])
    copied_issue_date = date.fromisoformat(copied["issueDate"])
    assert copied["installments"] == [
        {
            "dueDate": (
                copied_issue_date + (date.fromisoformat(installment["dueDate"]) - source_issue_date)
            ).isoformat(),
            "amount": installment["amount"],
        }
        for installment in original.json()["installments"]
    ]


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


async def test_invoice_listing_filters_by_customer(client):
    """Ver las facturas de un cliente exigía traerlas todas y filtrar en el
    navegador, sobre una lista que además viene acotada a 100."""
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix="filtro-a")
    otro = await client.post(
        "/api/v1/parties",
        headers=auth(token, "filtro-otro-party-000"),
        json={
            "name": "Cliente Sin Facturas",
            "identificationType": "CEDULA",
            "identificationNumber": "1790000009",
            "roles": ["CUSTOMER"],
        },
    )
    assert otro.status_code == 201, otro.text

    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    creada = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, "filtro-invoice-0001"),
        json=_invoice_payload(masters),
    )
    assert creada.status_code == 201, creada.text

    propias = await client.get(
        f"/api/v1/invoices?partyId={masters['party_id']}", headers=auth(token_invoices)
    )
    assert propias.status_code == 200, propias.text
    assert [item["id"] for item in propias.json()] == [creada.json()["id"]]

    ajenas = await client.get(
        f"/api/v1/invoices?partyId={otro.json()['id']}", headers=auth(token_invoices)
    )
    assert ajenas.status_code == 200, ajenas.text
    assert ajenas.json() == []

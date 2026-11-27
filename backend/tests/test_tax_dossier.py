"""Expediente del comprobante: factura, retencion, cobro y saldo en un lugar.

Verifica la comprobacion que pidio el usuario:
``total − retencion IVA − retencion renta = neto esperado``, y que una retencion
por si sola NO se cuente como cobro.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.tax import FiscalDocument, FiscalRetention, TaxPeriod
from app.services.tax import evidence as evidence_service
from app.services.tax import ingest as ingest_service

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TAX_SCOPES = ["tax:read", "tax:write"]

# Numero de la factura que respalda la retencion del fixture.
SUPPORTING_NUMBER = "001001000000045"


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    uploaded: dict[str, bytes] = {}

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs):
        uploaded[object_key] = data
        return None

    async def fake_download(*, object_key: str, **_kwargs) -> bytes:
        return uploaded[object_key]

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    monkeypatch.setattr(ingest_service.storage, "download_artifact", fake_download)
    return uploaded


async def token_for(client, scopes: list[str] = TAX_SCOPES) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": "a@iaerp.local", "tenantId": str(TENANT_A), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def seed_invoice_with_retention() -> uuid.UUID:
    """Factura emitida de 359.24 con una retencion de IVA 32.80 y renta 8.59."""
    async with SessionFactory() as session:
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2025,
            month=11,
            obligation_type="IVA",
            status="LISTO_REVISAR",
        )
        session.add(period)
        await session.flush()

        invoice = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="EMITIDO",
            doc_type="FACTURA",
            access_key="1511202501179999999900120010010000000451234567819",
            issue_date=date(2025, 11, 15),
            establishment_code="001",
            emission_point_code="001",
            sequential="000000045",
            counterparty_name="CLIENTE DEMO S.A.",
            subtotal=Decimal("312.38"),
            tax_total=Decimal("46.86"),
            total=Decimal("359.24"),
        )
        retention = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="RECIBIDO",
            doc_type="RETENCION",
            access_key="1011202507066666666600120010010000023643121521411",
            issue_date=date(2025, 11, 20),
            counterparty_name="CLIENTE AGENTE DEMO",
            total=Decimal("41.39"),
        )
        session.add_all([invoice, retention])
        await session.flush()

        session.add_all(
            [
                FiscalRetention(
                    tenant_id=TENANT_A,
                    fiscal_document_id=retention.id,
                    kind="IVA",
                    sri_code="2",
                    percentage=Decimal("70.00"),
                    base_amount=Decimal("46.86"),
                    retained_amount=Decimal("32.80"),
                    supporting_document_number=SUPPORTING_NUMBER,
                ),
                FiscalRetention(
                    tenant_id=TENANT_A,
                    fiscal_document_id=retention.id,
                    kind="RENTA",
                    sri_code="3440",
                    percentage=Decimal("2.75"),
                    base_amount=Decimal("312.38"),
                    retained_amount=Decimal("8.59"),
                    supporting_document_number=SUPPORTING_NUMBER,
                ),
            ]
        )
        await session.commit()
        return invoice.id


async def get_dossier(client, token: str, document_id: uuid.UUID) -> dict[str, Any]:
    response = await client.get(
        f"/api/v1/tax/documents/{document_id}/dossier", headers=auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_dossier_links_invoice_with_its_retention(client, stored_objects) -> None:
    token = await token_for(client)
    invoice_id = await seed_invoice_with_retention()

    body = await get_dossier(client, token, invoice_id)

    assert body["docType"] == "FACTURA"
    assert body["total"] == "359.24"
    assert len(body["retentions"]) == 1
    retention = body["retentions"][0]
    # IVA y renta se muestran SEPARADAS, como exige el ADR 0012.
    assert retention["ivaAmount"] == "32.80"
    assert retention["incomeTaxAmount"] == "8.59"
    assert retention["issuerName"] == "CLIENTE AGENTE DEMO"


async def test_expected_net_discounts_both_retentions(client, stored_objects) -> None:
    token = await token_for(client)
    invoice_id = await seed_invoice_with_retention()

    body = await get_dossier(client, token, invoice_id)

    # 359.24 − 32.80 − 8.59 = 317.85
    assert body["retainedIva"] == "32.80"
    assert body["retainedIncomeTax"] == "8.59"
    assert body["expectedNet"] == "317.85"


async def test_retention_alone_is_not_a_payment(client, stored_objects) -> None:
    token = await token_for(client)
    invoice_id = await seed_invoice_with_retention()

    body = await get_dossier(client, token, invoice_id)

    # Sin cartera enlazada no se inventa un cobro.
    assert body["collectedAmount"] == "0.00"
    assert body["movements"] == []
    assert body["receivableId"] is None


async def test_dossier_of_a_received_document_has_no_receivable(client, stored_objects) -> None:
    token = await token_for(client)
    await seed_invoice_with_retention()

    async with SessionFactory() as session:
        retention = await session.scalar(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == TENANT_A,
                FiscalDocument.doc_type == "RETENCION",
            )
        )
        assert retention is not None
        retention_id = retention.id

    body = await get_dossier(client, token, retention_id)

    assert body["direction"] == "RECIBIDO"
    assert body["receivableId"] is None
    # El comprobante muestra su propio desglose, sin mezclar IVA y renta.
    assert body["retainedIva"] == "32.80"
    assert body["retainedIncomeTax"] == "8.59"
    assert body["expectedNet"] == "0.00"
    assert len(body["retentions"]) == 1


async def test_dossier_requires_tax_read_scope(client) -> None:
    token = await token_for(client, ["parties:read"])
    response = await client.get(
        f"/api/v1/tax/documents/{uuid.uuid4()}/dossier", headers=auth(token)
    )
    assert response.status_code == 403


@pytest.mark.parametrize("support", [None, SUPPORTING_NUMBER])
async def test_bank_isd_stays_on_its_own_receipt(client, support) -> None:
    token = await token_for(client)
    invoice_id = await seed_invoice_with_retention()
    async with SessionFactory() as session, session.begin():
        invoice = await session.get(FiscalDocument, invoice_id)
        receipt = FiscalDocument(
            tenant_id=TENANT_A, tax_period_id=invoice.tax_period_id,
            direction="RECIBIDO", doc_type="RETENCION", issue_date=date(2025, 11, 21),
            access_key="7" * 49, counterparty_name="BANCO DEMO", total=Decimal("25.13"),
        )
        session.add(receipt)
        await session.flush()
        session.add(FiscalRetention(
            tenant_id=TENANT_A, fiscal_document_id=receipt.id, kind="ISD", sri_code="4580",
            percentage=Decimal("5"), base_amount=Decimal("502.50"),
            retained_amount=Decimal("25.13"), supporting_document_number=support,
        ))
        receipt_id = receipt.id

    dossier = await get_dossier(client, token, receipt_id)
    assert dossier["retainedIsd"] == dossier["total"] == "25.13"
    assert dossier["retentions"][0]["isdLines"] == [{
        "sriCode": "4580", "baseAmount": "502.50",
        "percentage": "5.0000", "retainedAmount": "25.13",
    }]
    assert dossier["retainedIncomeTax"] == dossier["retainedIva"] == "0.00"
    assert dossier["expectedNet"] == "0.00"
    assert dossier["receivableId"] is None
    assert dossier["movements"] == []
    sale = await get_dossier(client, token, invoice_id)
    assert sale["retainedIsd"] == "0.00"
    assert len(sale["retentions"]) == 1
    assert sale["expectedNet"] == "317.85"

    dashboard = await client.get(
        "/api/v1/tax/dashboard", params={"as_of": "2025-11-30"}, headers=auth(token)
    )
    assert dashboard.status_code == 200, dashboard.text
    annual = dashboard.json()["annual"]
    assert annual["isdWithheld"] == "25.13"
    assert annual["incomeTaxWithheld"] == "8.59"
    assert annual["ivaWithheld"] == "32.80"


async def test_unknown_document_returns_404(client) -> None:
    token = await token_for(client)
    response = await client.get(
        f"/api/v1/tax/documents/{uuid.uuid4()}/dossier", headers=auth(token)
    )
    assert response.status_code == 404


async def test_issued_purchase_liquidation_is_not_a_receivable(client, stored_objects):
    token = await token_for(client)
    invoice_id = await seed_invoice_with_retention()
    async with SessionFactory.begin() as session:
        document = await session.get(FiscalDocument, invoice_id)
        document.doc_type = "LIQUIDACION"
    body = await get_dossier(client, token, invoice_id)
    assert body["expectedNet"] == "0.00"
    assert not body["receivableId"]
    assert not body["retentions"]  # Una retención de venta con el mismo número es ajena.
    assert "Compras" in " ".join(body["notes"])
    assert "Importar mis ventas" not in " ".join(body["notes"])

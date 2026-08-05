"""Excepción ATS para una factura autorizada cuyo XML original se perdió."""

import hashlib
import uuid
from xml.etree.ElementTree import fromstring

from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.receivables import Receivable
from app.services.storage import UploadResult
from tests.conftest import TENANT_A
from tests.test_billing_api import _setup_billing_masters, auth, token_for
from tests.test_historical_invoice_pdf import _historical_pdf


async def test_historical_ride_requires_human_approval_then_enters_ats(
    client, monkeypatch
) -> None:
    setup_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    await _setup_billing_masters(client, setup_token, key_prefix="tax-historical-exception")

    pdf_data = _historical_pdf()

    async def fake_ride_upload(**_kwargs: object) -> UploadResult:
        return UploadResult(
            object_key="tenant/historical-ride.pdf",
            sha256=hashlib.sha256(pdf_data).hexdigest(),
            size_bytes=100,
        )

    monkeypatch.setattr(
        "app.services.historical_invoice_pdf.storage.upload_artifact", fake_ride_upload
    )
    invoice_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    historical = await client.post(
        "/api/v1/invoices/historical-pdf",
        headers=auth(invoice_token, "historical-tax-source-0001"),
        files={"file": ("factura-historica.pdf", pdf_data, "application/pdf")},
    )
    assert historical.status_code == 201, historical.text
    sales_document_id = historical.json()["id"]

    tax_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["tax:read", "tax:write"]
    )
    period = await client.post(
        "/api/v1/tax/periods",
        headers=auth(tax_token, "historical-tax-period-0001"),
        json={"year": 2026, "month": 5, "obligationType": "IVA"},
    )
    assert period.status_code == 201, period.text
    period_id = period.json()["id"]

    candidates = await client.get(
        f"/api/v1/tax/periods/{period_id}/historical-tax-candidates",
        headers=auth(tax_token),
    )
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()[0]["approved"] is False
    assert candidates.json()[0]["xmlOriginalMissing"] is True

    rejected = await client.post(
        f"/api/v1/tax/periods/{period_id}/historical-tax-candidates/"
        f"{sales_document_id}/approve",
        headers=auth(tax_token, "historical-tax-rejected-0001"),
        json={"confirmed": False, "evidenceReference": "Banco 15/05/2026"},
    )
    assert rejected.status_code == 422

    approved = await client.post(
        f"/api/v1/tax/periods/{period_id}/historical-tax-candidates/"
        f"{sales_document_id}/approve",
        headers=auth(tax_token, "historical-tax-approved-0001"),
        json={
            "confirmed": True,
            "evidenceReference": "Estado bancario 15/05/2026, transferencia neta respaldada",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["paymentMethods"] == ["20"]
    assert approved.json()["isPreliminary"] is False

    candidates = await client.get(
        f"/api/v1/tax/periods/{period_id}/historical-tax-candidates",
        headers=auth(tax_token),
    )
    assert candidates.json()[0]["approved"] is True

    stored: dict[str, bytes] = {}

    async def fake_private_upload(*, object_key: str, data: bytes, **_kwargs: object) -> None:
        stored[object_key] = data

    async def fake_download_url(**_kwargs: object) -> str:
        return "https://files.test/ats-mayo.zip"

    monkeypatch.setattr(
        "app.services.tax.annexes.storage.upload_private_object", fake_private_upload
    )
    monkeypatch.setattr(
        "app.services.tax.annexes.storage.generate_presigned_download_url",
        fake_download_url,
    )
    annex = await client.post(
        f"/api/v1/tax/periods/{period_id}/ats",
        headers=auth(tax_token, "historical-tax-annex-0001"),
    )
    assert annex.status_code == 201, annex.text
    xml = next(value for key, value in stored.items() if key.endswith(".xml"))
    root = fromstring(xml)
    assert root.findtext("totalVentas") == "100.00"
    assert root.findtext("ventas/detalleVentas/tipoComprobante") == "18"
    assert root.findtext("ventas/detalleVentas/formasDePago/formaPago") == "20"
    assert root.findtext("ventasEstablecimiento/ventaEst/ventasEstab") == "100.00"

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, uuid.UUID(sales_document_id))
        assert document is not None
        assert document.commercial_snapshot is not None
        exception = document.commercial_snapshot["tax_exception"]
        assert exception["xml_original_missing"] is True
        assert exception["scope"] == "IVA_ATS_ONLY"
        assert await session.scalar(select(func.count()).select_from(Receivable)) == 0

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.billing import DocumentArtifact, SalesDocument
from app.models.receivables import Receivable
from app.services import access_key
from app.services.historical_invoice_pdf import parse_historical_invoice_pdf
from app.services.storage import UploadResult
from app.services.tax.reporting import dashboard_tax_report
from tests.conftest import TENANT_A
from tests.test_billing_api import _setup_billing_masters, auth, token_for


def _historical_pdf() -> bytes:
    key = access_key.build_access_key(
        access_key.AccessKeyInput(
            issue_date=date(2026, 5, 11),
            document_code="01",
            ruc="1799999999001",
            environment="2",
            establishment_code="001",
            emission_point_code="001",
            sequential="000000123",
            numeric_code="12345678",
        )
    )
    lines = [
        "Tenant A",
        "R.U.C.: 1799999999001",
        "F A C T U R A",
        "No. 001-001-000000123",
        "NÚMERO DE AUTORIZACIÓN",
        key,
        "FECHA AUTORIZACIÓN: 2026-05-11 15:16:00-05:00",
        "AMBIENTE: PRODUCCIÓN",
        "CLAVE DE ACCESO",
        key,
        "Razón Social / Nombres y Apellidos: Cliente Facturable",
        "Identificación: 1790000001",
        "Fecha Emisión: 11/05/2026",
        "Cod.",
        "Cant.",
        "Descripción",
        "Precio Unitario",
        "Descuento",
        "Precio Total",
        "GEN",
        "1.00",
        "Servicio histórico respaldado",
        "100.00",
        "0.00",
        "100.00",
        "SUBTOTAL 15%",
        "100.00",
        "SUBTOTAL 0%",
        "0.00",
        "SUBTOTAL No Obj. IVA",
        "0.00",
        "SUBTOTAL Exento IVA",
        "0.00",
        "SUBTOTAL SIN IMPUESTOS",
        "100.00",
        "DESCUENTO",
        "0.00",
        "ICE",
        "0.00",
        "IVA 15%",
        "15.00",
        "PROPINA",
        "0.00",
        "VALOR TOTAL",
        "115.00",
    ]
    output = io.BytesIO()
    pdf = canvas.Canvas(output)
    y = 810
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 16
    pdf.save()
    return output.getvalue()


def test_parse_historical_pdf_validates_document_fields_and_totals() -> None:
    parsed = parse_historical_invoice_pdf(_historical_pdf())

    assert parsed.sequential == "000000123"
    assert parsed.customer_identification == "1790000001"
    assert parsed.subtotal == Decimal("100.00")
    assert parsed.tax_total == Decimal("15.00")
    assert parsed.total == Decimal("115.00")
    assert parsed.description == "Servicio histórico respaldado"


async def test_historical_pdf_creates_reporting_sale_without_tax_or_receivable(
    client, monkeypatch
) -> None:
    setup_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    await _setup_billing_masters(client, setup_token, key_prefix="historical-pdf")
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )

    async def fake_upload(**_kwargs: object) -> UploadResult:
        return UploadResult(
            object_key="tenant/historical-ride.pdf",
            sha256="a" * 64,
            size_bytes=100,
        )

    monkeypatch.setattr(
        "app.services.historical_invoice_pdf.storage.upload_artifact", fake_upload
    )
    response = await client.post(
        "/api/v1/invoices/historical-pdf",
        headers=auth(token, "historical-pdf-create-0001"),
        files={"file": ("factura-historica.pdf", _historical_pdf(), "application/pdf")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "HISTORICAL_ISSUED"
    assert body["sequential"] == "000000123"
    assert body["total"] == "115.00"
    assert body["collectionStatus"] is None
    assert body["sriTransmission"] is None

    async with SessionFactory() as session:
        document = await session.scalar(
            select(SalesDocument).where(SalesDocument.id == uuid.UUID(body["id"]))
        )
        assert document is not None
        assert document.commercial_snapshot is not None
        assert document.commercial_snapshot["reporting_only"] is True
        assert await session.scalar(select(func.count()).select_from(Receivable)) == 0
        assert await session.scalar(select(func.count()).select_from(DocumentArtifact)) == 1
        report = await dashboard_tax_report(
            session,
            AuthContext(
                actor_id="test",
                actor_type="USER",
                tenant_id=TENANT_A,
                roles=frozenset({"owner"}),
                scopes=frozenset({"tax:read"}),
                token_id="test",
            ),
            as_of=date(2026, 5, 31),
            months=1,
        )
        assert report.trend[0].total == Decimal("115.00")
        assert report.trend[0].invoice_count == 1
        assert report.current_month.authorized_sales_total == Decimal("0.00")


async def test_historical_pdf_rejects_a_second_document_with_same_access_key(
    client, monkeypatch
) -> None:
    setup_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    await _setup_billing_masters(client, setup_token, key_prefix="historical-duplicate")
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:write"])

    async def fake_upload(**_kwargs: object) -> UploadResult:
        return UploadResult(object_key="tenant/ride.pdf", sha256="b" * 64, size_bytes=100)

    monkeypatch.setattr(
        "app.services.historical_invoice_pdf.storage.upload_artifact", fake_upload
    )
    files = {"file": ("factura.pdf", _historical_pdf(), "application/pdf")}
    first = await client.post(
        "/api/v1/invoices/historical-pdf",
        headers=auth(token, "historical-first-0001"),
        files=files,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/invoices/historical-pdf",
        headers=auth(token, "historical-second-0001"),
        files={"file": ("factura.pdf", _historical_pdf(), "application/pdf")},
    )
    assert second.status_code == 409

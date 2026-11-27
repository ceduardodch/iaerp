"""Revisión por pago, sin inferir IVA desde la factura comercial o la liquidación."""

import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.tax import FiscalDocument, TaxPeriod
from tests.test_billing_api import TENANT_B
from tests.test_billing_api import token_for as tenant_token
from tests.test_tax_iva import FIXTURES, find_period, token_for, upload_and_ingest
from tests.test_tax_iva import auth as authorization
from tests.test_tax_iva import stored_objects as stored_objects  # noqa: PLC0414


def auth(token, key=None):
    return authorization(token, "tax-external-test-" + key if key else None)


async def test_external_review_uses_active_payments_only_and_preserves_amounts(client):
    token = await token_for(client, ["payables:read", "payables:write", "tax:write", "tax:read"])
    payable = await client.post(
        "/api/v1/payables",
        headers=auth(token, "create-abroad"),
        json={
            "description": "Servicio de monitoreo de ejemplo",
            "issueDate": "2025-10-24",
            "supplierName": "Proveedor Sintético",
            "documentNumber": "REF-DEMO",
            "total": "240.00",
            "foreignDigitalService": True,
        },
    )
    assert payable.status_code == 201, payable.text
    url = "/api/v1/payables/" + payable.json()["id"]
    for month in (10, 11, 12):
        period = await client.post(
            "/api/v1/tax/periods",
            headers=auth(token, f"period-{month}"),
            json={"year": 2025, "month": month, "obligationType": "IVA"},
        )
        assert period.status_code == 201
    for key, day, amount in [
        ("first", "2025-11-10", "50"),
        ("second", "2025-11-13", "20"),
        ("error", "2025-11-14", "30"),
        ("third", "2025-12-01", "40"),
    ]:
        paid = await client.post(
            url + "/payments",
            headers=auth(token, key),
            json={"amount": amount, "paymentDate": day, "method": "TRANSFER"},
        )
        assert paid.status_code == 201, paid.text
    history = (await client.get(url + "/movements", headers=auth(token))).json()
    wrong = next(m for m in history if m["effectiveDate"] == "2025-11-14")
    reversal = await client.post(
        url + "/movements/" + wrong["id"] + "/reversal",
        headers=auth(token, "reverse-error"),
        json={"effectiveDate": "2025-11-15", "reason": "Pago duplicado"},
    )
    assert reversal.status_code == 201
    for month, total in [(10, None), (11, "70.00"), (12, "40.00")]:
        period_id = (await find_period(client, token, 2025, month))["id"]
        summary = (
            await client.get(f"/api/v1/tax/periods/{period_id}/iva", headers=auth(token))
        ).json()
        assert summary["requiresExternalReview"] is bool(total)
        assert summary["amounts"]["ivaCreditoTributario"] == "0.00"
        if total:
            assert any(
                "REF-DEMO" in r and f"USD {total}" in r for r in summary["preliminaryReasons"]
            )
            ats = await client.post(
                f"/api/v1/tax/periods/{period_id}/ats", headers=auth(token, f"ats-{month}"), json={}
            )
            assert ats.status_code == 422
            assert "REF-DEMO" in ats.json()["detail"]
    other = await tenant_token(client, "b@iaerp.local", TENANT_B, ["tax:read", "tax:write"])
    period = await client.post(
        "/api/v1/tax/periods",
        headers=auth(other, "period-b"),
        json={"year": 2025, "month": 11, "obligationType": "IVA"},
    )
    summary = (
        await client.get("/api/v1/tax/periods/" + period.json()["id"] + "/iva", headers=auth(other))
    ).json()
    assert not summary["requiresExternalReview"]
    assert "REF-DEMO" not in str(summary)


async def test_issued_liquidation_no_sales_or_credit_and_external_iva_acknowledgment(
    client, stored_objects
):
    token = await token_for(client)
    # Mismo molde SRI autorizado, con los campos propios de la liquidación de compra.
    xml = (FIXTURES / "factura_recibida_iva15.xml").read_text()
    xml = (
        xml.replace("<factura>", "<liquidacionCompra>")
        .replace("</factura>", "</liquidacionCompra>")
        .replace("infoFactura", "infoLiquidacionCompra")
        .replace("Comprador", "Proveedor")
        .replace("0888888888001", "1799999999001")
        .replace("<codDoc>01", "<codDoc>03")
    )
    await upload_and_ingest(client, token, "liquidacion.xml", content=xml.encode())
    period = await find_period(client, token, 2025, 11)
    assert period["status"] == "EVIDENCIA_INCOMPLETA"
    base = "/api/v1/tax/periods/" + period["id"]
    summary = (await client.get(base + "/iva", headers=auth(token))).json()
    assert summary["requiresExternalReview"]
    for field in ("ventasNetas", "ivaGenerado", "ivaCreditoTributario", "saldoAPagar"):
        assert summary["amounts"][field] == "0.00"
    doc = (await client.get(base + "/documents", headers=auth(token))).json()[0]
    assert doc["counterpartyIdentification"] == "0777777777001"
    ats = await client.post(base + "/ats", headers=auth(token, "block-ats"), json={})
    assert ats.status_code == 422
    assert "liquidaciones" in ats.json()["detail"]

    async def status(target, evidence=None):
        return await client.post(
            base + "/status",
            headers=auth(token, str(uuid.uuid4())),
            json={"confirmed": True, "targetStatus": target, "externalFilingEvidenceId": evidence},
        )

    assert (await status("LISTO_DECLARAR")).status_code == 409
    assert (await status("DECLARADO", str(uuid.uuid4()))).status_code == 422
    receipt_bytes = b"%PDF-synthetic"
    original = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "generic-receipt"),
        data={"origin": "MANUAL", "taxPeriodId": period["id"]},
        files={"file": ("comp.pdf", receipt_bytes, "application/pdf")},
    )
    assert original.status_code == 201
    assert (await status("DECLARADO", original.json()["id"])).status_code == 422
    file = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "iva-receipt"),
        data={"origin": "ACUSE_IVA_SRI", "taxPeriodId": period["id"]},
        files={"file": ("acuse.pdf", b"%PDF-synthetic", "application/pdf")},
    )
    assert file.status_code == 201, file.text
    assert file.json()["id"] == original.json()["id"]
    assert file.json()["duplicate"]
    wrong_month = await client.post(
        "/api/v1/tax/periods",
        headers=auth(token, "other-month"),
        json={"year": 2025, "month": 12, "obligationType": "IVA"},
    )
    cross_period = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "cross-period"),
        data={"origin": "ACUSE_IVA_SRI", "taxPeriodId": wrong_month.json()["id"]},
        files={"file": ("same-receipt.pdf", receipt_bytes, "application/pdf")},
    )
    assert cross_period.status_code == 409
    result = await status("DECLARADO", file.json()["id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "DECLARADO"
    summary = (await client.get(base + "/iva", headers=auth(token))).json()
    assert summary["isPreliminary"]
    annual = (
        await client.get(
            "/api/v1/tax/dashboard", headers=auth(token), params={"as_of": "2025-11-30"}
        )
    ).json()
    assert annual["currentMonth"]["evidencedSalesCount"] == 0
    assert annual["annual"]["declaredSalesBase"] == "0.00"
    assert (
        await client.post(base + "/ats", headers=auth(token, "block-ats-after-filing"), json={})
    ).status_code == 422


async def test_731_uses_issued_authorized_iva_retention_once(client, stored_objects):
    token = await token_for(client)
    received = (FIXTURES / "retencion_recibida_autorizada.xml").read_text()
    await upload_and_ingest(client, token, "recibida.xml", content=received.encode())
    issued = (
        received.replace("0666666666001", "1799999999001")
        .replace("1011202501066666666600120010010000000461234567818", "7" * 49)
        .replace("<porcentajeRetener>70.00", "<porcentajeRetener>100.00")
        .replace("<valorRetenido>32.80", "<valorRetenido>46.86")
        .replace("<codigoRetencion>2<", "<codigoRetencion>3<")
    )
    for _ in range(2):
        await upload_and_ingest(client, token, "emitida.xml", content=issued.encode())
    period = await find_period(client, token, 2025, 11)
    summary = (
        await client.get(f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token))
    ).json()
    fields = {row["fieldCode"]: row for row in summary["fields"]}
    assert fields["731"]["value"] == "46.86"
    assert fields["731"]["documentCount"] == 1
    assert fields["609"]["value"] == "32.80"
    assert summary["amounts"]["ivaCreditoTributario"] == "0.00"
    assert summary["amounts"]["saldoAPagar"] == "0.00"
    assert summary["amounts"]["creditoAFavor"] == "32.80"


@pytest.mark.parametrize(
    "note_code,note_tag,info_tag",
    [("04", "notaCredito", "infoNotaCredito"), ("05", "notaDebito", "infoNotaDebito")],
)
@pytest.mark.parametrize("legacy_key_only", [False, True])
async def test_issued_notes_of_prior_liquidation_are_not_sales(
    client, stored_objects, note_code, note_tag, info_tag, legacy_key_only
):
    token = await token_for(client)
    template = (
        (FIXTURES / "factura_recibida_iva15.xml")
        .read_text()
        .replace("0888888888001", "1799999999001")
    )
    template_key = "1111202501098888888800120010020000198772795212911"
    source_key = "1110202503" + "1" * 39
    note_key = "11112025" + note_code + "2" * 39
    source = (
        template.replace("factura>", "liquidacionCompra>")
        .replace("infoFactura", "infoLiquidacionCompra")
        .replace("Comprador", "Proveedor")
        .replace("11/11/2025", "11/10/2025")
        .replace("<codDoc>01", "<codDoc>03")
        .replace(template_key, source_key)
    )
    note = (
        template.replace("factura>", note_tag + ">")
        .replace("infoFactura", info_tag)
        .replace("<codDoc>01", "<codDoc>" + note_code)
        .replace(template_key, note_key)
        .replace("000019877</secuencial>", "000019878</secuencial>")
        .replace(
            "<fechaEmision>",
            "<codDocModificado>03</codDocModificado>"
            "<numDocModificado>001-002-000019877</numDocModificado><fechaEmision>",
        )
    )
    await upload_and_ingest(client, token, "nota.xml", content=note.encode())
    november = await find_period(client, token, 2025, 11)
    path = "/api/v1/tax/periods/" + november["id"]
    # El tipo del sustento basta aunque la liquidación todavía no se haya importado.
    assert (await client.get(path + "/iva", headers=auth(token))).json()["requiresExternalReview"]
    await upload_and_ingest(client, token, "liquidacion.xml", content=source.encode())
    async with SessionFactory.begin() as session:
        row = (
            await session.scalars(
                select(FiscalDocument).where(FiscalDocument.access_key == note_key)
            )
        ).one()
        assert row.related_access_key == source_key
        if legacy_key_only:
            row.related_document_type = None
        # Simula noviembre histórico ya presentado.
        stored_period = await session.get(TaxPeriod, uuid.UUID(november["id"]))
        stored_period.status = "DECLARADO"
    summary = (await client.get(path + "/iva", headers=auth(token))).json()
    assert summary["requiresExternalReview"]
    assert summary["amounts"]["ivaGenerado"] == summary["amounts"]["ventasNetas"] == "0.00"
    [document] = (await client.get(path + "/documents", headers=auth(token))).json()
    assert document["isIssuedPurchase"]
    dossier = (
        await client.get(
            "/api/v1/tax/documents/" + document["id"] + "/dossier", headers=auth(token)
        )
    ).json()
    assert dossier["isIssuedPurchase"]
    assert dossier["expectedNet"] == "0.00"
    assert dossier["receivableId"] is None
    ats = await client.post(path + "/ats", headers=auth(token, "ats-nov"), json={})
    assert ats.status_code == 422
    assert "liquidaciones" in ats.json()["detail"]
    dashboard = (
        await client.get(
            "/api/v1/tax/dashboard", headers=auth(token), params={"as_of": "2025-11-30"}
        )
    ).json()
    assert dashboard["annual"]["declaredSalesBase"] == "0.00"
    assert dashboard["currentMonth"]["evidencedSalesCount"] == 0

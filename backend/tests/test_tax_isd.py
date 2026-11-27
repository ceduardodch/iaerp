"""Retenciones bancarias sintéticas con y sin una factura de sustento."""

from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionFactory
from app.models.receivables import Movement
from app.models.tax import FiscalDocument, FiscalRetention
from app.services.tax.sri_xml import parse_authorized_document
from tests.test_tax_bulk import auth, find_period, post_bulk, token_for
from tests.test_tax_bulk import stored_objects as stored_objects  # noqa: F401
from tests.test_tax_receivable_retention_sync import RUC, balance, ingest, setup_invoice

ISD = ("6", "4580", "207.50", "5", "10.38")
RENTA = ("1", "323E", "100.00", "3", "3.00")
IVA = ("2", "2", "15.00", "70", "10.50")


def retention_xml(version, lines, *, issuer="0990000000001", support=None):
    authorization = "5" * 49
    support_tags = "<codDocSustento>00</codDocSustento>"
    if support:
        support_tags = (
            f"<codDocSustento>01</codDocSustento><numDocSustento>{support}</numDocSustento>"
        )
    rows = []
    for tax, concept, base, rate, withheld in lines:
        fields = (
            f"<codigo>{tax}</codigo><codigoRetencion>{concept}</codigoRetencion>"
            f"<baseImponible>{base}</baseImponible><porcentajeRetener>{rate}</porcentajeRetener>"
            f"<valorRetenido>{withheld}</valorRetenido>"
        )
        if version == "1.0.0":
            rows.append(f"<impuesto>{fields}{support_tags}</impuesto>")
        else:
            rows.append(f"<retencion>{fields}</retencion>")
    detail = "".join(rows)
    if version == "1.0.0":
        detail = f"<impuestos>{detail}</impuestos>"
    else:
        detail = (
            f"<docsSustento><docSustento>{support_tags}<retenciones>{detail}</retenciones>"
            "</docSustento></docsSustento>"
        )
    return f"""<autorizacion><estado>AUTORIZADO</estado>
<numeroAutorizacion>{authorization}</numeroAutorizacion><comprobante><![CDATA[
<comprobanteRetencion version="{version}"><infoTributaria><ruc>{issuer}</ruc>
<razonSocial>EMISOR SINTETICO</razonSocial><codDoc>07</codDoc>
<claveAcceso>{authorization}</claveAcceso>
<estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000000123</secuencial></infoTributaria>
<infoCompRetencion><fechaEmision>14/08/2026</fechaEmision>
<identificacionSujetoRetenido>{RUC}</identificacionSujetoRetenido></infoCompRetencion>
{detail}</comprobanteRetencion>]]></comprobante></autorizacion>""".encode()


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_isd_keeps_the_declared_amount_without_an_invoice(version):
    document = parse_authorized_document(retention_xml(version, [ISD]))
    assert document.total == Decimal("10.38")
    [item] = document.retentions
    assert item.kind == "ISD"
    assert item.sri_code == "4580"
    assert item.base_amount == Decimal("207.50")
    assert item.percentage == Decimal("5")
    assert item.retained_amount == Decimal("10.38")
    assert item.supporting_document_number is None


async def test_isd_mixed_receipt_reimport_and_tax_summary(client, stored_objects):
    token = await token_for(client)
    file = ("mixto.xml", retention_xml("2.0.0", [RENTA, ISD, IVA]), "application/xml")
    preview = await post_bulk(client, token, [], extra_files=[file])
    assert preview["items"][0]["total"] == "23.88"
    for created_count in [1, 0]:
        result = await post_bulk(client, token, [], extra_files=[file], apply=True)
        assert result["created"] == created_count
        assert result["errors"] == 0
    async with SessionFactory() as session:
        [document] = list(await session.scalars(select(FiscalDocument)))
        assert document.total == Decimal("23.88")
        rows = list(await session.scalars(select(FiscalRetention)))
        assert sorted(row.kind for row in rows) == ["ISD", "IVA", "RENTA"]
        assert list(await session.scalars(select(Movement))) == []
    period = await find_period(client, token, 2026, 8)
    response = await client.get(f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token))
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["amounts"]["retencionesIsdRecibidas"] == "10.38"
    assert summary["amounts"]["retencionesRentaRecibidas"] == "3.00"
    assert summary["amounts"]["retencionesIvaRecibidas"] == "10.50"
    field_609 = next(item for item in summary["fields"] if item["fieldCode"] == "609")
    assert field_609["value"] == "10.50"
    dashboard = await client.get(
        "/api/v1/tax/dashboard", headers=auth(token), params={"as_of": "2026-08-31"}
    )
    assert dashboard.status_code == 200, dashboard.text
    annual = dashboard.json()["annual"]
    assert annual["incomeTaxWithheld"] == "3.00"
    assert annual["ivaWithheld"] == "10.50"


@pytest.mark.parametrize(
    ("lines", "expected_balance", "expected_movements"),
    [([ISD], "100.00", []), ([ISD, IVA, RENTA], "86.50", ["3.00", "10.50"])],
)
async def test_isd_never_settles_even_a_matching_invoice(
    lines, expected_balance, expected_movements
):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        payload = retention_xml("2.0.0", lines, issuer=party.identification_number, support=number)
        for _ in range(2):
            await ingest(session, payload)
        assert await balance(session, debt) == Decimal(expected_balance)
        amounts = list(await session.scalars(select(Movement.amount).order_by(Movement.amount)))
        assert amounts == [Decimal(value) for value in expected_movements]


async def test_reingesting_authorized_evidence_repairs_a_zero_isd_receipt(client, stored_objects):
    token = await token_for(client)
    xml = retention_xml("1.0.0", [ISD])
    files = [("banco.xml", xml, "application/xml")]
    preview = await post_bulk(client, token, [], extra_files=files)
    assert preview["retentionCount"] == 0
    [item] = preview["items"]
    assert item["docType"] == "RETENCION"
    assert item["isRetention"] is False
    assert item["total"] == "10.38"

    first = await post_bulk(client, token, [], extra_files=files, apply=True)
    assert first["created"] == 1
    async with SessionFactory() as session, session.begin():
        [document] = list(await session.scalars(select(FiscalDocument)))
        document_id, evidence_id = document.id, document.evidence_id
        assert evidence_id is not None
        # Reproduce el registro histórico que conservó el XML pero omitió todo el ISD.
        await session.execute(
            delete(FiscalRetention).where(FiscalRetention.fiscal_document_id == document_id)
        )
        document.total = Decimal("0.00")

    recovered = await client.post(
        f"/api/v1/tax/evidence/{evidence_id}/ingest",
        headers=auth(token, "isd-reingesta-historica"),
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["updated"] == 1
    async with SessionFactory() as session:
        [repaired] = list(await session.scalars(select(FiscalDocument)))
        assert (repaired.id, repaired.evidence_id) == (document_id, evidence_id)
        assert repaired.total == Decimal("10.38")
        [isd] = list(await session.scalars(select(FiscalRetention)))
        assert isd.fiscal_document_id == document_id
        assert isd.retained_amount == Decimal("10.38")
        assert list(await session.scalars(select(Movement))) == []

"""Lectura segura de XML SRI de retención antes de registrar un cobro."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.receivables import Receivable
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_payments_api import _create_receivable_via_event


def _retention_xml(
    *,
    authorization: str,
    issuer_ruc: str,
    retained_ruc: str,
    support: str,
    status: str = "AUTORIZADO",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion>
  <estado>{status}</estado>
  <numeroAutorizacion>{authorization}</numeroAutorizacion>
  <comprobante><![CDATA[<comprobanteRetencion>
    <infoTributaria><ruc>{issuer_ruc}</ruc><claveAcceso>{authorization}</claveAcceso></infoTributaria>
    <infoCompRetencion><identificacionSujetoRetenido>{retained_ruc}</identificacionSujetoRetenido></infoCompRetencion>
    <docsSustento><docSustento><numDocSustento>{support}</numDocSustento><retenciones>
      <retencion><codigo>1</codigo><codigoRetencion>3440</codigoRetencion><baseImponible>100.00</baseImponible><porcentajeRetener>3</porcentajeRetener><valorRetenido>3.00</valorRetenido></retencion>
      <retencion><codigo>2</codigo><codigoRetencion>2</codigoRetencion><baseImponible>15.00</baseImponible><porcentajeRetener>70</porcentajeRetener><valorRetenido>10.50</valorRetenido></retencion>
    </retenciones></docSustento></docsSustento>
  </comprobanteRetencion>]]></comprobante>
</autorizacion>""".encode()


def _legacy_retention_xml(
    *, authorization: str, issuer_ruc: str, retained_ruc: str, support: str
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>{authorization}</numeroAutorizacion>
<comprobante><![CDATA[<comprobanteRetencion>
  <infoTributaria><ruc>{issuer_ruc}</ruc><claveAcceso>{authorization}</claveAcceso></infoTributaria>
  <infoCompRetencion><identificacionSujetoRetenido>{retained_ruc}</identificacionSujetoRetenido></infoCompRetencion>
  <impuestos><impuesto><codigo>2</codigo><codigoRetencion>2</codigoRetencion><baseImponible>15.00</baseImponible><porcentajeRetener>100</porcentajeRetener><valorRetenido>15.00</valorRetenido><numDocSustento>{support}</numDocSustento></impuesto></impuestos>
</comprobanteRetencion>]]></comprobante></autorizacion>""".encode()


async def _setup_preview_receivable(client) -> tuple[str, str, str]:
    setup = await _create_receivable_via_event(
        key_prefix="ret-preview", sequential="000000951", total=Decimal("150.00")
    )
    receivable_id, masters = await setup(client)
    issuer_ruc = "1790000000001"
    async with SessionFactory() as session:
        party = await session.get(Party, uuid.UUID(masters["party_id"]))
        assert party is not None
        party.identification_type = "RUC"
        party.identification_number = issuer_ruc
        receivable = await session.get(Receivable, uuid.UUID(receivable_id))
        assert receivable is not None
        assert await session.scalar(select(Receivable).where(Receivable.id == receivable.id))
        await session.commit()
    return receivable_id, issuer_ruc, "001001000000951"


async def test_preview_authorized_retention_xml_loads_exact_amounts(client) -> None:
    receivable_id, issuer_ruc, support = await _setup_preview_receivable(client)
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    authorization = "1" * 49
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/retention-preview",
        headers=auth(token),
        files={
            "file": (
                "retencion.xml",
                _retention_xml(
                    authorization=authorization,
                    issuer_ruc=issuer_ruc,
                    retained_ruc="1799999999001",
                    support=support,
                ),
                "application/xml",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["authorizationNumber"] == authorization
    assert body["supportingDocument"] == support
    assert body["retentions"] == [
        {
            "kind": "RETENTION_RENTA",
            "amount": "3.00",
            "baseAmount": "100.00",
            "rate": "3",
            "sriRetentionCode": "3440",
        },
        {
            "kind": "RETENTION_IVA",
            "amount": "10.50",
            "baseAmount": "15.00",
            "rate": "70",
            "sriRetentionCode": "2",
        },
    ]


async def test_preview_accepts_legacy_sri_retention_xml(client) -> None:
    receivable_id, issuer_ruc, support = await _setup_preview_receivable(client)
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/retention-preview",
        headers=auth(token),
        files={
            "file": (
                "retencion-v1.xml",
                _legacy_retention_xml(
                    authorization="3" * 49,
                    issuer_ruc=issuer_ruc,
                    retained_ruc="1799999999001",
                    support=support,
                ),
                "application/xml",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["retentions"][0]["amount"] == "15.00"


@pytest.mark.parametrize(
    "status,issuer_ruc",
    [("NO AUTORIZADO", "1790000000001"), ("AUTORIZADO", "1790000000002")],
)
async def test_preview_rejects_untrusted_or_unrelated_retention_xml(
    client, status: str, issuer_ruc: str
) -> None:
    receivable_id, expected_issuer_ruc, support = await _setup_preview_receivable(client)
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/retention-preview",
        headers=auth(token),
        files={
            "file": (
                "retencion.xml",
                _retention_xml(
                    authorization="2" * 49,
                    issuer_ruc=issuer_ruc if status == "AUTORIZADO" else expected_issuer_ruc,
                    retained_ruc="1799999999001",
                    support=support,
                    status=status,
                ),
                "application/xml",
            )
        },
    )
    assert response.status_code == 422

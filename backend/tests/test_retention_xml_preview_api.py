"""Lectura segura de XML SRI de retención antes de registrar un cobro."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.platform import AuditEvent
from app.models.receivables import Movement, Receivable
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_payments_api import _create_receivable_via_event


def _retention_xml(
    *,
    authorization: str,
    issuer_ruc: str,
    retained_ruc: str,
    support: str,
    status: str = "AUTORIZADO",
    issue_date: str = "10/07/2026",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion>
  <estado>{status}</estado>
  <numeroAutorizacion>{authorization}</numeroAutorizacion>
  <comprobante><![CDATA[<comprobanteRetencion>
    <infoTributaria><ruc>{issuer_ruc}</ruc><claveAcceso>{authorization}</claveAcceso></infoTributaria>
    <infoCompRetencion><fechaEmision>{issue_date}</fechaEmision><identificacionSujetoRetenido>{retained_ruc}</identificacionSujetoRetenido></infoCompRetencion>
    <docsSustento><docSustento><numDocSustento>{support}</numDocSustento><retenciones>
      <retencion><codigo>1</codigo><codigoRetencion>3440</codigoRetencion><baseImponible>100.00</baseImponible><porcentajeRetener>3</porcentajeRetener><valorRetenido>3.00</valorRetenido></retencion>
      <retencion><codigo>2</codigo><codigoRetencion>2</codigoRetencion><baseImponible>15.00</baseImponible><porcentajeRetener>70</porcentajeRetener><valorRetenido>10.50</valorRetenido></retencion>
    </retenciones></docSustento></docsSustento>
  </comprobanteRetencion>]]></comprobante>
</autorizacion>""".encode()


def _legacy_retention_xml(
    *,
    authorization: str,
    issuer_ruc: str,
    retained_ruc: str,
    support: str,
    issue_date: str = "15/06/2025",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>{authorization}</numeroAutorizacion>
<comprobante><![CDATA[<comprobanteRetencion>
  <infoTributaria><ruc>{issuer_ruc}</ruc><claveAcceso>{authorization}</claveAcceso></infoTributaria>
  <infoCompRetencion><fechaEmision>{issue_date}</fechaEmision><identificacionSujetoRetenido>{retained_ruc}</identificacionSujetoRetenido></infoCompRetencion>
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
    assert body["issueDate"] == "2026-07-10"
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
    assert response.json()["issueDate"] == "2025-06-15"
    assert response.json()["retentions"][0]["amount"] == "15.00"


async def test_batch_preview_then_registers_matched_xml_once(client) -> None:
    receivable_id, issuer_ruc, support = await _setup_preview_receivable(client)
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    authorization = "4" * 49
    xml = _retention_xml(
        authorization=authorization,
        issuer_ruc=issuer_ruc,
        retained_ruc="1799999999001",
        support=support,
    )

    preview = await client.post(
        "/api/v1/receivables/retention-batch",
        headers=auth(token),
        data={"apply": "false"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"] == [
        {
            "fileName": "retencion.xml",
            "receivableId": receivable_id,
            "authorizationNumber": authorization,
            "supportingDocument": support,
            "invoiceSequential": "000000951",
            "issueDate": "2026-07-10",
            "total": "13.50",
            "status": "MATCHED",
            "detail": "Lista para registrar",
        }
    ]

    headers = {**auth(token), "Idempotency-Key": "retention-batch-register-0001"}
    first = await client.post(
        "/api/v1/receivables/retention-batch",
        headers=headers,
        data={"apply": "true"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert first.status_code == 200, first.text
    assert first.json()["items"][0]["detail"] == "Registrada"

    repeated = await client.post(
        "/api/v1/receivables/retention-batch",
        headers=headers,
        data={"apply": "true"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first.json()
    async with SessionFactory() as session:
        receivable = await session.get(Receivable, uuid.UUID(receivable_id))
        assert receivable is not None
        movements = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(receivable_id),
                    Movement.movement_type == "RETENTION",
                )
            )
        )
    assert len(movements) == 2
    assert {movement.effective_date for movement in movements} == {date(2026, 7, 10)}

    invoice_token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    invoice = await client.get(
        f"/api/v1/invoices/{receivable.sales_document_id}", headers=auth(invoice_token)
    )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["retentionTotal"] == "13.50"


async def test_reupload_corrects_historical_retention_date_with_audit(client) -> None:
    receivable_id, issuer_ruc, support = await _setup_preview_receivable(client)
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    authorization = "5" * 49
    xml = _retention_xml(
        authorization=authorization,
        issuer_ruc=issuer_ruc,
        retained_ruc="1799999999001",
        support=support,
        issue_date="15/06/2025",
    )
    first = await client.post(
        "/api/v1/receivables/retention-batch",
        headers={**auth(token), "Idempotency-Key": "retention-history-first-0001"},
        data={"apply": "true"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert first.status_code == 200, first.text

    async with SessionFactory() as session:
        movements = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(receivable_id),
                    Movement.movement_type == "RETENTION",
                )
            )
        )
        for movement in movements:
            movement.effective_date = date(2026, 8, 2)
        await session.commit()

    preview = await client.post(
        "/api/v1/receivables/retention-batch",
        headers=auth(token),
        data={"apply": "false"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["status"] == "MATCHED"
    assert preview.json()["items"][0]["issueDate"] == "2025-06-15"
    assert preview.json()["items"][0]["detail"] == "Corregirá la fecha desde el XML"

    corrected = await client.post(
        "/api/v1/receivables/retention-batch",
        headers={**auth(token), "Idempotency-Key": "retention-history-correct-0001"},
        data={"apply": "true"},
        files={"files": ("retencion.xml", xml, "application/xml")},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["items"][0]["detail"] == "Fecha corregida desde el XML"
    async with SessionFactory() as session:
        corrected_movements = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(receivable_id),
                    Movement.movement_type == "RETENTION",
                )
            )
        )
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == TENANT_A,
                AuditEvent.action == "retention.effective_date_corrected",
                AuditEvent.entity_id == receivable_id,
            )
        )
    assert {movement.effective_date for movement in corrected_movements} == {
        date(2025, 6, 15)
    }
    assert audit is not None
    assert audit.details["previous_dates"] == ["2026-08-02"]
    assert audit.details["effective_date"] == "2025-06-15"


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

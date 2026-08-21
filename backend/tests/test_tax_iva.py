"""Motor de IVA mensual y campos del formulario (E3).

Verifica las reglas que definio el usuario: las ventas salen de los emitidos (no
de las retenciones), las notas de credito restan, las compras se separan por
tramo, y la retencion de IVA (609) va aparte de la de renta.

El flujo completo se ejercita por la API: subir evidencia -> ingerir -> calcular.
"""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.payables import Payable, PayableMovement
from app.models.tax import FiscalDocument
from app.services.tax import evidence as evidence_service
from tests.fixtures.sri_documents import CREDIT_NOTE_RECEIVED_IVA15_XML

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TAX_SCOPES = ["tax:read", "tax:write"]

# RUC del tenant demo: los comprobantes de los fixtures van dirigidos a el, asi
# que se clasifican como RECIBIDOS.
DEMO_RECEIVER = "0777777777001"


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    """Sustituye MinIO por memoria: guarda y devuelve el mismo contenido."""
    uploaded: dict[str, bytes] = {}

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs):
        uploaded[object_key] = data
        return None

    async def fake_download(*, object_key: str, **_kwargs) -> bytes:
        return uploaded[object_key]

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    from app.services.tax import ingest as ingest_service

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


async def upload_and_ingest(
    client,
    token: str,
    filename: str,
    *,
    content: bytes | None = None,
) -> dict[str, Any]:
    content = content if content is not None else (FIXTURES / filename).read_bytes()
    upload = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, f"tax-ev-{uuid.uuid4()}"),
        files={"file": (filename, content, "application/octet-stream")},
        data={"origin": "PORTAL_SRI"},
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]

    ingest = await client.post(
        f"/api/v1/tax/evidence/{evidence_id}/ingest",
        headers=auth(token, f"tax-in-{uuid.uuid4()}"),
    )
    assert ingest.status_code == 200, ingest.text
    return ingest.json()


async def find_period(client, token: str, year: int, month: int) -> dict[str, Any]:
    listed = await client.get(
        "/api/v1/tax/periods", headers=auth(token), params={"year": year}
    )
    assert listed.status_code == 200
    period = next(
        item for item in listed.json() if item["month"] == month and item["obligationType"] == "IVA"
    )
    return period


async def test_ingest_assigns_period_by_real_issue_date(client, stored_objects) -> None:
    token = await token_for(client)
    result = await upload_and_ingest(client, token, "factura_recibida_autorizada.xml")

    assert result["created"] == 1
    # El comprobante se emitio el 30/11/2025: debe caer en el periodo 2025-11.
    period = await find_period(client, token, 2025, 11)
    assert period["status"] == "LISTO_REVISAR"

    documents = await client.get(
        f"/api/v1/tax/periods/{period['id']}/documents", headers=auth(token)
    )
    assert documents.status_code == 200
    body = documents.json()
    assert len(body) == 1
    assert body[0]["direction"] == "RECIBIDO"
    assert body[0]["docType"] == "FACTURA"
    assert body[0]["issueDate"] == "2025-11-30"


async def test_reingesting_same_evidence_does_not_duplicate(client, stored_objects) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")

    period = await find_period(client, token, 2025, 11)
    documents = await client.get(
        f"/api/v1/tax/periods/{period['id']}/documents", headers=auth(token)
    )
    assert len(documents.json()) == 1


async def test_purchases_split_by_bracket_and_credit(client, stored_objects) -> None:
    token = await token_for(client)
    # Una compra gravada al 15% y otra con tarifa 0%.
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")
    await upload_and_ingest(client, token, "factura_recibida_autorizada.xml")

    period = await find_period(client, token, 2025, 11)
    response = await client.get(
        f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token)
    )
    assert response.status_code == 200
    amounts = response.json()["amounts"]

    assert amounts["comprasGravadasBase"] == "13.13"
    assert amounts["comprasTarifaCeroBase"] == "276.30"
    assert amounts["comprasTotalesBase"] == "289.43"
    assert amounts["ivaCreditoTributario"] == "1.97"
    # No hubo ventas: nada se infiere desde las compras.
    assert amounts["ventasBrutas"] == "0.00"
    assert amounts["ivaGenerado"] == "0.00"


@pytest.mark.parametrize(
    "filenames",
    [
        ("factura_recibida_iva15.xml", "nota_credito.xml"),
        ("nota_credito.xml", "factura_recibida_iva15.xml"),
    ],
)
async def test_received_credit_note_links_in_any_upload_order_and_reduces_payable(
    client,
    stored_objects,
    filenames: tuple[str, str],
) -> None:
    token = await token_for(client)
    for filename in filenames:
        await upload_and_ingest(
            client,
            token,
            filename,
            content=(CREDIT_NOTE_RECEIVED_IVA15_XML if filename == "nota_credito.xml" else None),
        )
    # La misma evidencia se puede procesar otra vez sin duplicar el ajuste.
    await upload_and_ingest(
        client,
        token,
        "nota_credito.xml",
        content=CREDIT_NOTE_RECEIVED_IVA15_XML,
    )

    period = await find_period(client, token, 2025, 11)
    iva = await client.get(
        f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token)
    )
    assert iva.status_code == 200, iva.text
    amounts = iva.json()["amounts"]
    assert amounts["comprasGravadasBase"] == "8.13"
    assert amounts["ivaCreditoTributario"] == "1.22"

    async with SessionFactory() as session:
        invoice = await session.scalar(
            select(FiscalDocument).where(FiscalDocument.doc_type == "FACTURA")
        )
        note = await session.scalar(
            select(FiscalDocument).where(FiscalDocument.doc_type == "NOTA_CREDITO")
        )
        assert invoice is not None
        assert note is not None
        assert note.related_document_number == "001-002-000019877"
        assert note.related_document_type == "FACTURA"
        assert note.related_access_key == invoice.access_key

        payable = await session.scalar(
            select(Payable).where(Payable.fiscal_document_id == invoice.id)
        )
        assert payable is not None
        movements = list(
            await session.scalars(
                select(PayableMovement).where(
                    PayableMovement.payable_id == payable.id,
                    PayableMovement.movement_type == "CREDIT_NOTE",
                )
            )
        )
        assert len(movements) == 1
        assert movements[0].amount == Decimal("5.75")
        assert payable.total - sum(
            (movement.amount for movement in movements), Decimal("0.00")
        ) == Decimal("9.35")
        assert payable.status == "PARTIALLY_PAID"


async def test_preliminary_txt_credit_note_never_creates_payable_movement(
    client,
    stored_objects,
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")

    content = (
        "RUC_EMISOR\tRAZON_SOCIAL_EMISOR\tTIPO_COMPROBANTE\tSERIE_COMPROBANTE\t"
        "CLAVE_ACCESO\tFECHA_AUTORIZACION\tFECHA_EMISION\tIDENTIFICACION_RECEPTOR\t"
        "VALOR_SIN_IMPUESTOS\tIVA\tIMPORTE_TOTAL\tNUMERO_DOCUMENTO_MODIFICADO\n"
        "0888888888001\tPROVEEDOR IVA DEMO\tNota de crédito\t001-002-000000112\t"
        "2211202504098888888800120010020000001121234567811\t22/11/2025\t"
        "22/11/2025\t0777777777001\t5.00\t0.75\t5.75\t001-002-000019877\n"
    ).encode("iso-8859-1")
    upload = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "tax-credit-note-txt-evidence"),
        files={"file": ("notas.txt", content, "text/plain")},
        data={"origin": "PORTAL_SRI"},
    )
    assert upload.status_code == 201, upload.text
    ingested = await client.post(
        f"/api/v1/tax/evidence/{upload.json()['id']}/ingest",
        headers=auth(token, "tax-credit-note-txt-ingest"),
    )
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["preliminary"] == 1

    async with SessionFactory() as session:
        note = await session.scalar(
            select(FiscalDocument).where(FiscalDocument.doc_type == "NOTA_CREDITO")
        )
        movement_count = len(
            list(
                await session.scalars(
                    select(PayableMovement).where(
                        PayableMovement.movement_type == "CREDIT_NOTE"
                    )
                )
            )
        )
    assert note is not None
    assert note.is_preliminary is True
    assert note.related_document_number == "001-002-000019877"
    assert note.related_access_key is not None
    assert movement_count == 0


async def test_credit_note_with_unsupported_modified_type_is_not_auto_linked(
    client,
    stored_objects,
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")
    invalid_relation = CREDIT_NOTE_RECEIVED_IVA15_XML.replace(
        b"<codDocModificado>01</codDocModificado>",
        b"<codDocModificado>07</codDocModificado>",
    )
    await upload_and_ingest(
        client,
        token,
        "nota_credito_tipo_no_soportado.xml",
        content=invalid_relation,
    )

    async with SessionFactory() as session:
        note = await session.scalar(
            select(FiscalDocument).where(FiscalDocument.doc_type == "NOTA_CREDITO")
        )
        movement = await session.scalar(
            select(PayableMovement).where(
                PayableMovement.movement_type == "CREDIT_NOTE"
            )
        )
    assert note is not None
    assert note.related_document_type == "RETENCION"
    assert note.related_access_key is None
    assert movement is None


async def test_credit_note_does_not_reopen_void_payable(client, stored_objects) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")
    async with SessionFactory.begin() as session:
        payable = await session.scalar(select(Payable))
        assert payable is not None
        payable.status = "VOID"

    await upload_and_ingest(
        client,
        token,
        "nota_credito.xml",
        content=CREDIT_NOTE_RECEIVED_IVA15_XML,
    )

    async with SessionFactory() as session:
        payable = await session.scalar(select(Payable))
        movement = await session.scalar(
            select(PayableMovement).where(
                PayableMovement.movement_type == "CREDIT_NOTE"
            )
        )
    assert payable is not None
    assert payable.status == "VOID"
    assert movement is None


async def test_authorized_credit_note_cannot_be_relinked_after_application(
    client,
    stored_objects,
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")
    await upload_and_ingest(
        client,
        token,
        "nota_credito.xml",
        content=CREDIT_NOTE_RECEIVED_IVA15_XML,
    )
    changed_relation = CREDIT_NOTE_RECEIVED_IVA15_XML.replace(
        b"001-002-000019877", b"001-002-000019878"
    )
    upload = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "tax-credit-note-relink-evidence"),
        files={"file": ("nota_credito_relink.xml", changed_relation, "application/xml")},
        data={"origin": "PORTAL_SRI"},
    )
    assert upload.status_code == 201, upload.text
    rejected = await client.post(
        f"/api/v1/tax/evidence/{upload.json()['id']}/ingest",
        headers=auth(token, "tax-credit-note-relink-ingest"),
    )
    assert rejected.status_code == 409, rejected.text

    async with SessionFactory() as session:
        note = await session.scalar(
            select(FiscalDocument).where(FiscalDocument.doc_type == "NOTA_CREDITO")
        )
        movements = list(
            await session.scalars(
                select(PayableMovement).where(
                    PayableMovement.movement_type == "CREDIT_NOTE"
                )
            )
        )
    assert note is not None
    assert note.related_document_number == "001-002-000019877"
    assert len(movements) == 1


async def test_purchase_list_uses_received_xml_and_exposes_tax_breakdown(
    client, stored_objects
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")

    response = await client.get(
        "/api/v1/tax/purchases",
        headers=auth(token),
        params={"year": 2025, "month": 11},
    )

    assert response.status_code == 200, response.text
    purchases = response.json()
    assert len(purchases) == 1
    assert purchases[0]["docType"] == "FACTURA"
    assert purchases[0]["supplierName"]
    assert purchases[0]["documentNumber"]
    assert purchases[0]["subtotal"] == "13.13"
    assert purchases[0]["taxTotal"] == "1.97"
    assert purchases[0]["total"] == "15.10"
    assert purchases[0]["isPreliminary"] is False
    assert purchases[0]["taxes"] == [
        {
            "sriTaxCode": "4",
            "taxBracket": "GRAVADO",
            "rate": "15.00",
            "baseAmount": "13.13",
            "taxAmount": "1.97",
        }
    ]


async def test_purchase_month_filter_requires_year(client) -> None:
    token = await token_for(client)
    response = await client.get(
        "/api/v1/tax/purchases", headers=auth(token), params={"month": 11}
    )
    assert response.status_code == 422


async def test_dashboard_marks_purchase_credit_as_accounting_review(
    client, stored_objects
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")

    response = await client.get(
        "/api/v1/tax/dashboard",
        headers=auth(token),
        params={"as_of": "2025-11-30"},
    )

    assert response.status_code == 200, response.text
    current = response.json()["currentMonth"]
    assert current["purchasesTotal"] == "15.10"
    assert current["ivaCredit"] == "1.97"
    assert current["ivaCreditBalance"] == "1.97"
    assert current["needsAccountingReview"] is True
    assert current["isPreliminary"] is True
    assert any("campo 564" in reason for reason in current["preliminaryReasons"])


async def test_purchase_and_dashboard_reads_require_tax_read_scope(client) -> None:
    token = await token_for(client, ["tax:write"])

    purchases = await client.get("/api/v1/tax/purchases", headers=auth(token))
    dashboard = await client.get("/api/v1/tax/dashboard", headers=auth(token))

    assert purchases.status_code == 403
    assert dashboard.status_code == 403


async def test_retention_feeds_609_and_keeps_income_tax_apart(client, stored_objects) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "retencion_recibida_autorizada.xml")

    period = await find_period(client, token, 2025, 11)
    response = await client.get(
        f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token)
    )
    body = response.json()
    amounts = body["amounts"]

    # Regla del usuario: el 609 es SOLO la retencion de IVA.
    assert amounts["retencionesIvaRecibidas"] == "32.80"
    assert amounts["retencionesRentaRecibidas"] == "8.59"

    field_609 = next(field for field in body["fields"] if field["fieldCode"] == "609")
    assert field_609["value"] == "32.80"
    assert field_609["isPaste"] is True
    # La retencion de renta NO alimenta ningun campo del IVA mensual.
    assert all(field["value"] != "8.59" for field in body["fields"])


async def test_form_fields_separate_paste_from_control(client, stored_objects) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")

    period = await find_period(client, token, 2025, 11)
    body = (
        await client.get(f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token))
    ).json()

    codes = {field["fieldCode"]: field for field in body["fields"]}
    assert {"401", "411", "500", "510", "517", "609"} <= set(codes)

    # El derecho a credito de 500/510 requiere revisar el destino contable.
    assert codes["510"]["isPaste"] is False
    assert codes["510"]["needsReview"] is True
    assert codes["500"]["isPaste"] is False
    assert codes["500"]["sourceKey"] == "comprasGravadasBrutaBase"
    assert codes["500"]["needsReview"] is True
    # El 507 fue contrastado con la guia vigente del SRI: bruto, tarifa 0%.
    assert codes["507"]["sourceKey"] == "comprasTarifaCeroBrutaBase"
    assert codes["507"]["isPaste"] is True
    assert codes["507"]["needsReview"] is False
    # El 411 es el valor neto de ventas gravadas, no ventas con tarifa 0%.
    assert codes["411"]["sourceKey"] == "ventasGravadasBase"
    # El 564 depende de proporcionalidad o contabilidad: no se copia sin revisar.
    assert codes["564"]["isPaste"] is False
    assert codes["564"]["needsReview"] is True
    assert codes["609"]["needsReview"] is False

    # Todos los valores salen con punto decimal y dos decimales.
    for field in body["fields"]:
        assert "," not in field["value"]
        assert field["value"].split(".")[-1].__len__() == 2


async def test_txt_only_period_is_reported_as_preliminary(client, stored_objects) -> None:
    token = await token_for(client)
    result = await upload_and_ingest(client, token, "recibidos_portal.txt")

    # Las retenciones del TXT llegan sin valores: se marcan preliminares.
    assert result["preliminary"] >= 1

    period = await find_period(client, token, 2025, 12)
    assert period["status"] == "EVIDENCIA_INCOMPLETA"
    body = (
        await client.get(f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token))
    ).json()

    assert body["isPreliminary"] is True
    assert any("XML" in reason for reason in body["preliminaryReasons"])


async def test_empty_period_reports_missing_evidence(client, stored_objects) -> None:
    token = await token_for(client)
    created = await client.post(
        "/api/v1/tax/periods",
        headers=auth(token, f"tax-p-{uuid.uuid4()}"),
        json={"year": 2026, "month": 3, "obligationType": "IVA"},
    )
    period_id = created.json()["id"]

    body = (
        await client.get(f"/api/v1/tax/periods/{period_id}/iva", headers=auth(token))
    ).json()

    assert body["documentCount"] == 0
    assert body["isPreliminary"] is True
    assert any("evidencia" in reason for reason in body["preliminaryReasons"])
    assert body["amounts"]["saldoAPagar"] == "0.00"


async def test_period_requires_human_confirmation_before_declared(
    client, stored_objects
) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "factura_recibida_iva15.xml")
    period = await find_period(client, token, 2025, 11)
    assert period["status"] == "LISTO_REVISAR"

    rejected = await client.post(
        f"/api/v1/tax/periods/{period['id']}/status",
        headers=auth(token, f"tax-status-{uuid.uuid4()}"),
        json={"targetStatus": "LISTO_DECLARAR", "confirmed": False},
    )
    assert rejected.status_code == 422

    skipped = await client.post(
        f"/api/v1/tax/periods/{period['id']}/status",
        headers=auth(token, f"tax-status-{uuid.uuid4()}"),
        json={"targetStatus": "DECLARADO", "confirmed": True},
    )
    assert skipped.status_code == 409

    ready = await client.post(
        f"/api/v1/tax/periods/{period['id']}/status",
        headers=auth(token, f"tax-status-{uuid.uuid4()}"),
        json={"targetStatus": "LISTO_DECLARAR", "confirmed": True},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "LISTO_DECLARAR"

    declared = await client.post(
        f"/api/v1/tax/periods/{period['id']}/status",
        headers=auth(token, f"tax-status-{uuid.uuid4()}"),
        json={"targetStatus": "DECLARADO", "confirmed": True},
    )
    assert declared.status_code == 200, declared.text
    assert declared.json()["status"] == "DECLARADO"


async def test_preliminary_period_cannot_be_marked_ready(client, stored_objects) -> None:
    token = await token_for(client)
    await upload_and_ingest(client, token, "recibidos_portal.txt")
    period = await find_period(client, token, 2025, 12)

    response = await client.post(
        f"/api/v1/tax/periods/{period['id']}/status",
        headers=auth(token, f"tax-status-{uuid.uuid4()}"),
        json={"targetStatus": "LISTO_DECLARAR", "confirmed": True},
    )
    assert response.status_code == 409

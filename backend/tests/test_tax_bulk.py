"""Carga en bloque de comprobantes del SRI.

El usuario sube la carpeta completa de un mes y el sistema debe clasificar cada
archivo por su contenido, ubicarlo en el periodo de su **fecha real de emision**
y no escribir nada hasta que se confirme.
"""

import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, func, select

from app.db.session import SessionFactory
from app.models.tax import FiscalDocument, FiscalRetention
from app.services.tax import evidence as evidence_service
from app.services.tax import ingest as ingest_service

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TAX_SCOPES = ["tax:read", "tax:write"]


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    """MinIO en memoria para no depender de Docker."""
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


def fixture_file(name: str) -> tuple[str, bytes, str]:
    return (name, (FIXTURES / name).read_bytes(), "application/octet-stream")


def legacy_retention_xml() -> bytes:
    authorization = "6" * 49
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>{authorization}</numeroAutorizacion>
<fechaAutorizacion>2025-06-16T09:00:00-05:00</fechaAutorizacion>
<comprobante><![CDATA[<comprobanteRetencion version="1.0.0">
  <infoTributaria><ruc>0666666666001</ruc><razonSocial>CLIENTE HISTORICO</razonSocial>
    <claveAcceso>{authorization}</claveAcceso><estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000000321</secuencial></infoTributaria>
  <infoCompRetencion><fechaEmision>15/06/2025</fechaEmision>
    <identificacionSujetoRetenido>1799999999001</identificacionSujetoRetenido>
    <razonSocialSujetoRetenido>EMPRESA PRUEBA</razonSocialSujetoRetenido></infoCompRetencion>
  <impuestos>
    <impuesto><codigo>1</codigo><codigoRetencion>3440</codigoRetencion><baseImponible>100.00</baseImponible><porcentajeRetener>3.00</porcentajeRetener><valorRetenido>3.00</valorRetenido><numDocSustento>001001000000951</numDocSustento></impuesto>
    <impuesto><codigo>2</codigo><codigoRetencion>2</codigoRetencion><baseImponible>15.00</baseImponible><porcentajeRetener>70.00</porcentajeRetener><valorRetenido>10.50</valorRetenido><numDocSustento>001001000000951</numDocSustento></impuesto>
  </impuestos>
</comprobanteRetencion>]]></comprobante></autorizacion>""".encode()


async def post_bulk(
    client,
    token: str,
    names: list[str],
    *,
    apply: bool = False,
    extra_files: list[tuple[str, bytes, str]] | None = None,
) -> dict[str, Any]:
    files = [("files", fixture_file(name)) for name in names]
    files.extend(("files", item) for item in (extra_files or []))
    data: dict[str, str] = {"apply": "true" if apply else "false"}
    headers = auth(token, f"tax-bulk-{uuid.uuid4()}") if apply else auth(token)
    response = await client.post(
        "/api/v1/tax/evidence/bulk",
        headers=headers,
        files=files,
        data=data,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def list_documents(client, token: str, period_id: str) -> list[dict[str, Any]]:
    response = await client.get(
        f"/api/v1/tax/periods/{period_id}/documents", headers=auth(token)
    )
    assert response.status_code == 200
    return response.json()


async def find_period(client, token: str, year: int, month: int) -> dict[str, Any] | None:
    listed = await client.get("/api/v1/tax/periods", headers=auth(token), params={"year": year})
    assert listed.status_code == 200
    return next(
        (
            item
            for item in listed.json()
            if item["month"] == month and item["obligationType"] == "IVA"
        ),
        None,
    )


async def test_preview_classifies_each_file_without_writing(client, stored_objects) -> None:
    token = await token_for(client)
    body = await post_bulk(
        client,
        token,
        [
            "factura_recibida_iva15.xml",
            "factura_recibida_autorizada.xml",
            "retencion_recibida_autorizada.xml",
        ],
    )

    kinds = {item["filename"]: item for item in body["items"]}
    assert kinds["factura_recibida_iva15.xml"]["docType"] == "FACTURA"
    assert kinds["retencion_recibida_autorizada.xml"]["docType"] == "RETENCION"
    # Los comprobantes van dirigidos al tenant: son RECIBIDOS.
    assert all(item["direction"] == "RECIBIDO" for item in kinds.values())
    # La retencion recibida es la que puede aplicarse a cartera.
    assert kinds["retencion_recibida_autorizada.xml"]["isRetention"] is True
    assert body["retentionCount"] == 1

    # El previo NO escribe: no hay periodos ni documentos todavia.
    assert await find_period(client, token, 2025, 11) is None
    assert body["created"] == 0


async def test_preview_assigns_period_by_real_issue_date(client, stored_objects) -> None:
    token = await token_for(client)
    body = await post_bulk(
        client,
        token,
        ["factura_recibida_iva15.xml", "factura_recibida_autorizada.xml"],
    )

    # Emitidas el 11/11 y el 30/11: ambas al periodo 2025-11.
    for item in body["items"]:
        assert item["periodYear"] == 2025
        assert item["periodMonth"] == 11
    assert body["periods"] == {"2025-11": 2}


async def test_apply_registers_documents_in_their_periods(client, stored_objects) -> None:
    token = await token_for(client)
    body = await post_bulk(
        client,
        token,
        [
            "factura_recibida_iva15.xml",
            "factura_recibida_autorizada.xml",
            "retencion_recibida_autorizada.xml",
        ],
        apply=True,
    )

    assert body["created"] == 3
    period = await find_period(client, token, 2025, 11)
    assert period is not None
    documents = await list_documents(client, token, period["id"])
    assert len(documents) == 3
    assert {doc["docType"] for doc in documents} == {"FACTURA", "RETENCION"}


async def test_applying_twice_does_not_duplicate(client, stored_objects) -> None:
    token = await token_for(client)
    names = ["factura_recibida_iva15.xml", "factura_recibida_autorizada.xml"]

    first = await post_bulk(client, token, names, apply=True)
    second = await post_bulk(client, token, names, apply=True)

    assert first["created"] == 2
    # El segundo lote no crea nada nuevo: mismo hash y misma clave de acceso.
    assert second["created"] == 0

    period = await find_period(client, token, 2025, 11)
    assert period is not None
    assert len(await list_documents(client, token, period["id"])) == 2


async def test_reapplying_legacy_xml_repairs_missing_historical_detail(
    client, stored_objects
) -> None:
    token = await token_for(client)
    xml = legacy_retention_xml()
    files = [("retencion-v1.xml", xml, "application/xml")]
    first = await post_bulk(client, token, [], apply=True, extra_files=files)
    assert first["created"] == 1

    async with SessionFactory() as session:
        document = await session.scalar(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == TENANT_A,
                FiscalDocument.access_key == "6" * 49,
            )
        )
        assert document is not None
        await session.execute(
            delete(FiscalRetention).where(
                FiscalRetention.tenant_id == TENANT_A,
                FiscalRetention.fiscal_document_id == document.id,
            )
        )
        await session.commit()

    repaired = await post_bulk(client, token, [], apply=True, extra_files=files)
    assert repaired["created"] == 0
    assert repaired["updated"] == 1
    async with SessionFactory() as session:
        retention_count = await session.scalar(
            select(func.count(FiscalRetention.id)).where(
                FiscalRetention.tenant_id == TENANT_A,
                FiscalRetention.fiscal_document_id == document.id,
            )
        )
        documents = await session.scalar(
            select(func.count(FiscalDocument.id)).where(
                FiscalDocument.tenant_id == TENANT_A,
                FiscalDocument.access_key == "6" * 49,
            )
        )
    assert retention_count == 2
    assert documents == 1


async def test_unreadable_file_does_not_abort_the_batch(client, stored_objects) -> None:
    token = await token_for(client)
    body = await post_bulk(
        client,
        token,
        ["factura_recibida_iva15.xml"],
        apply=True,
        extra_files=[("roto.xml", b"<esto no es un comprobante/>", "application/xml")],
    )

    # El archivo bueno se registra y el malo se reporta con su motivo.
    assert body["created"] == 1
    assert body["errors"] == 1
    failed = next(item for item in body["items"] if item["filename"] == "roto.xml")
    assert failed["status"] == "ERROR"
    assert failed["error"]


async def test_zip_is_expanded_into_its_receipts(client, stored_objects) -> None:
    token = await token_for(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "factura_a.xml", (FIXTURES / "factura_recibida_iva15.xml").read_bytes()
        )
        archive.writestr(
            "factura_b.xml", (FIXTURES / "factura_recibida_autorizada.xml").read_bytes()
        )
        # Metadato que agrega macOS: no debe procesarse.
        archive.writestr("__MACOSX/._factura_a.xml", b"basura")

    body = await post_bulk(
        client,
        token,
        [],
        extra_files=[("mes.zip", buffer.getvalue(), "application/zip")],
    )

    procesados = [item for item in body["items"] if item["status"] != "ERROR"]
    assert len(procesados) == 2
    assert all(item["sourceArchive"] == "mes.zip" for item in procesados)


async def test_pdf_is_reported_as_evidence_only(client, stored_objects) -> None:
    token = await token_for(client)
    body = await post_bulk(
        client,
        token,
        [],
        extra_files=[("retencion.pdf", b"%PDF-1.4 demo", "application/pdf")],
    )

    item = body["items"][0]
    assert item["status"] == "ERROR"
    assert "XML" in (item["error"] or "")


async def test_bulk_requires_tax_write_scope(client) -> None:
    token = await token_for(client, ["tax:read"])
    response = await client.post(
        "/api/v1/tax/evidence/bulk",
        headers=auth(token),
        files=[("files", fixture_file("factura_recibida_iva15.xml"))],
        data={"apply": "false"},
    )
    assert response.status_code == 403


async def test_apply_requires_idempotency_key(client, stored_objects) -> None:
    token = await token_for(client)
    response = await client.post(
        "/api/v1/tax/evidence/bulk",
        headers=auth(token),
        files=[("files", fixture_file("factura_recibida_iva15.xml"))],
        data={"apply": "true"},
    )
    assert response.status_code == 422

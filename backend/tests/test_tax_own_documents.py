"""Importacion de los comprobantes que la propia entidad emitio (ventas).

Los emitidos no se descargan del portal: IAERP ya los firma y guarda el XML como
artefacto ``xml-signed``, con la autorizacion en ``SRITransmission``. Este flujo
los trae al modulo tributario para que las ventas del periodo no dependan de que
el usuario suba sus propios comprobantes.

Reglas verificadas (ADR 0012): solo AUTORIZADOS, el detalle sale del XML real, y
lo que no tiene respaldo se omite informando el motivo, sin inventar nada.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.billing import DocumentArtifact, SalesDocument, SRITransmission
from app.models.tax import FiscalDocument
from app.services.tax import own_documents

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TAX_SCOPES = ["tax:read", "tax:write"]

ACCESS_KEY = "1511202501179999999900120010010000000451234567819"

# Factura emitida por la entidad, en el formato que IAERP guarda: el comprobante
# FIRMADO, sin el sobre <autorizacion> (ese solo existe para lo descargado).
SIGNED_INVOICE = f"""<?xml version="1.0" encoding="UTF-8"?>
<factura id="comprobante" version="2.1.0">
  <infoTributaria>
    <ambiente>2</ambiente>
    <tipoEmision>1</tipoEmision>
    <razonSocial>IAERP Demo</razonSocial>
    <ruc>1799999999001</ruc>
    <claveAcceso>{ACCESS_KEY}</claveAcceso>
    <codDoc>01</codDoc>
    <estab>001</estab>
    <ptoEmi>001</ptoEmi>
    <secuencial>000000045</secuencial>
    <dirMatriz>DIRECCION DEMO</dirMatriz>
  </infoTributaria>
  <infoFactura>
    <fechaEmision>15/11/2025</fechaEmision>
    <obligadoContabilidad>SI</obligadoContabilidad>
    <tipoIdentificacionComprador>04</tipoIdentificacionComprador>
    <razonSocialComprador>CLIENTE DEMO S.A.</razonSocialComprador>
    <identificacionComprador>0666666666001</identificacionComprador>
    <totalSinImpuestos>312.38</totalSinImpuestos>
    <totalDescuento>0</totalDescuento>
    <totalConImpuestos>
      <totalImpuesto>
        <codigo>2</codigo>
        <codigoPorcentaje>4</codigoPorcentaje>
        <baseImponible>312.38</baseImponible>
        <tarifa>15.00</tarifa>
        <valor>46.86</valor>
      </totalImpuesto>
    </totalConImpuestos>
    <importeTotal>359.24</importeTotal>
    <moneda>DOLAR</moneda>
    <pagos><pago><formaPago>20</formaPago><total>359.24</total></pago></pagos>
  </infoFactura>
</factura>"""


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    """MinIO en memoria: el XML firmado se sirve desde aqui."""
    uploaded: dict[str, bytes] = {}

    async def fake_download(*, object_key: str, **_kwargs) -> bytes:
        return uploaded[object_key]

    monkeypatch.setattr(own_documents.storage, "download_artifact", fake_download)
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


async def setup_masters(client, _token: str | None = None) -> dict[str, uuid.UUID]:
    """Crea los maestros minimos que exige una factura.

    Usa su propio token: crear maestros necesita scopes de organizacion y
    contactos, no los de `tax:*`.
    """
    token = await token_for(client, ["organization:write", "parties:write"])
    establishment = await client.post(
        "/api/v1/establishments",
        headers=auth(token, f"tax-est-{uuid.uuid4()}"),
        json={"code": "001", "name": "Matriz", "address": "Direccion demo"},
    )
    assert establishment.status_code == 201, establishment.text
    establishment_id = uuid.UUID(establishment.json()["id"])

    emission_point = await client.post(
        "/api/v1/emission-points",
        headers=auth(token, f"tax-ep-{uuid.uuid4()}"),
        json={"establishmentId": str(establishment_id), "code": "001"},
    )
    assert emission_point.status_code == 201, emission_point.text

    party = await client.post(
        "/api/v1/parties",
        headers=auth(token, f"tax-party-{uuid.uuid4()}"),
        json={
            "name": "CLIENTE DEMO S.A.",
            "identificationType": "RUC",
            "identificationNumber": "0666666666001",
            "roles": ["CUSTOMER"],
        },
    )
    assert party.status_code == 201, party.text

    return {
        "establishment_id": establishment_id,
        "emission_point_id": uuid.UUID(emission_point.json()["id"]),
        "party_id": uuid.UUID(party.json()["id"]),
    }


async def seed_authorized_invoice(
    stored_objects: dict[str, bytes],
    masters: dict[str, uuid.UUID],
    *,
    with_artifact: bool = True,
    with_authorization: bool = True,
) -> uuid.UUID:
    """Crea una factura AUTORIZADA como la que emitiria IAERP."""
    async with SessionFactory() as session:
        document = SalesDocument(
            tenant_id=TENANT_A,
            document_type="INVOICE",
            establishment_id=masters["establishment_id"],
            emission_point_id=masters["emission_point_id"],
            sequential="000000045",
            access_key=ACCESS_KEY,
            party_id=masters["party_id"],
            issue_date=date(2025, 11, 15),
            status="AUTHORIZED",
            subtotal=Decimal("312.38"),
            tax_total=Decimal("46.86"),
            total=Decimal("359.24"),
            fiscal_policy_version="2025.1",
        )
        session.add(document)
        await session.flush()

        if with_authorization:
            session.add(
                SRITransmission(
                    tenant_id=TENANT_A,
                    sales_document_id=document.id,
                    access_key=ACCESS_KEY,
                    status="AUTHORIZED",
                    authorization_number=ACCESS_KEY,
                    authorized_at=datetime(2025, 11, 15, 18, 0, tzinfo=UTC),
                )
            )

        if with_artifact:
            object_key = f"{TENANT_A}/invoices/{document.id}/signed.xml"
            stored_objects[object_key] = SIGNED_INVOICE.encode("utf-8")
            session.add(
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=document.id,
                    artifact_type="xml-signed",
                    object_key=object_key,
                    sha256="0" * 64,
                    version=1,
                )
            )

        await session.commit()
        return document.id


async def create_period(client, token: str, year: int = 2025, month: int = 11) -> str:
    response = await client.post(
        "/api/v1/tax/periods",
        headers=auth(token, f"tax-p-{uuid.uuid4()}"),
        json={"year": year, "month": month, "obligationType": "IVA"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_imports_issued_invoice_as_sale(client, stored_objects) -> None:
    token = await token_for(client)
    masters = await setup_masters(client, token)
    sales_document_id = await seed_authorized_invoice(stored_objects, masters)
    period_id = await create_period(client, token)

    response = await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1

    documents = await client.get(
        f"/api/v1/tax/periods/{period_id}/documents", headers=auth(token)
    )
    body = documents.json()
    assert len(body) == 1
    # Se registra como VENTA de la entidad, con el detalle leido del XML real.
    assert body[0]["direction"] == "EMITIDO"
    assert body[0]["docType"] == "FACTURA"
    assert body[0]["issueDate"] == "2025-11-15"
    assert body[0]["subtotal"] == "312.38"
    assert body[0]["taxTotal"] == "46.86"
    assert body[0]["isPreliminary"] is False

    async with SessionFactory() as session:
        fiscal = await session.scalar(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == TENANT_A,
                FiscalDocument.access_key == ACCESS_KEY,
            )
        )
        assert fiscal is not None
        # Queda enlazado con la factura que lo origino.
        assert fiscal.sales_document_id == sales_document_id


async def test_imported_sale_feeds_the_iva_summary(client, stored_objects) -> None:
    token = await token_for(client)
    await seed_authorized_invoice(stored_objects, await setup_masters(client, token))
    period_id = await create_period(client, token)

    await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )

    summary = (
        await client.get(f"/api/v1/tax/periods/{period_id}/iva", headers=auth(token))
    ).json()

    # Las ventas y el IVA generado salen del comprobante emitido.
    assert summary["amounts"]["ventasGravadasBase"] == "312.38"
    assert summary["amounts"]["ivaGenerado"] == "46.86"
    # Sin compras cargadas no hay credito: no se infiere nada.
    assert summary["amounts"]["ivaCreditoTributario"] == "0.00"


async def test_importing_twice_does_not_duplicate(client, stored_objects) -> None:
    token = await token_for(client)
    await seed_authorized_invoice(stored_objects, await setup_masters(client, token))
    period_id = await create_period(client, token)

    first = await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )
    second = await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )

    assert first.json()["created"] == 1
    assert second.json()["created"] == 0
    assert second.json()["updated"] == 1

    documents = await client.get(
        f"/api/v1/tax/periods/{period_id}/documents", headers=auth(token)
    )
    assert len(documents.json()) == 1


async def test_invoice_without_authorization_is_skipped_with_reason(
    client, stored_objects
) -> None:
    token = await token_for(client)
    masters = await setup_masters(client, token)
    await seed_authorized_invoice(stored_objects, masters, with_authorization=False)
    period_id = await create_period(client, token)

    response = await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )
    body = response.json()

    # Sin autorizacion del SRI no es evidencia: se omite y se explica.
    assert body["created"] == 0
    assert body["skipped"] == 1
    assert any("autorizacion" in note.lower() for note in body["notes"])


async def test_invoice_without_signed_xml_is_skipped_with_reason(
    client, stored_objects
) -> None:
    token = await token_for(client)
    masters = await setup_masters(client, token)
    await seed_authorized_invoice(stored_objects, masters, with_artifact=False)
    period_id = await create_period(client, token)

    body = (
        await client.post(
            f"/api/v1/tax/periods/{period_id}/import-issued",
            headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
        )
    ).json()

    # El detalle debe salir del XML real; sin el, no se reconstruye a mano.
    assert body["created"] == 0
    assert body["skipped"] == 1
    assert any("xml" in note.lower() for note in body["notes"])


async def test_import_requires_tax_write_scope(client) -> None:
    token = await token_for(client, ["tax:read"])
    period_id = uuid.uuid4()
    response = await client.post(
        f"/api/v1/tax/periods/{period_id}/import-issued",
        headers=auth(token, f"tax-imp-{uuid.uuid4()}"),
    )
    assert response.status_code == 403

"""Fundacion del modulo tributario (E1): periodos y evidencia.

Cubre las reglas del ADR 0012 que se pueden verificar en esta etapa:

- La evidencia se identifica por su hash: subir el mismo archivo dos veces NO
  duplica evidencia (devuelve el registro existente marcado como duplicado).
- Un PDF se guarda como evidencia pero queda anotado como "no se leen sus
  valores automaticamente" (los valores salen del XML/TXT).
- Los periodos son unicos por entidad/anio/mes/obligacion y nacen en
  `PENDIENTE_DESCARGA`.
- Todo el modulo es tenant-scoped y exige los scopes `tax:read`/`tax:write`.
"""

import uuid
from typing import Any

import pytest

from app.services.tax import evidence as evidence_service

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

TAX_SCOPES = ["tax:read", "tax:write"]


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    """Evita MinIO real: captura en memoria lo que se subiria al bucket."""
    uploaded: dict[str, bytes] = {}

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs):
        uploaded[object_key] = data
        return None

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    return uploaded


async def token_for(client, email: str, tenant_id: uuid.UUID, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def create_period(client, token: str, **overrides: Any) -> dict[str, Any]:
    payload = {"year": 2025, "month": 10, "obligationType": "IVA"}
    payload.update(overrides)
    response = await client.post(
        "/api/v1/tax/periods",
        headers=auth(token, f"tax-period-{uuid.uuid4()}"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def upload_evidence(
    client,
    token: str,
    *,
    filename: str,
    content: bytes,
    period_id: str | None = None,
) -> dict[str, Any]:
    data = {"origin": "PORTAL_SRI"}
    if period_id:
        data["taxPeriodId"] = period_id
    response = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, f"tax-evidence-{uuid.uuid4()}"),
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_period_is_created_pending_download_and_is_unique(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)

    created = await create_period(client, token)
    assert created["status"] == "PENDIENTE_DESCARGA"
    assert created["year"] == 2025
    assert created["month"] == 10
    assert created["obligationType"] == "IVA"

    # Mismo anio/mes/obligacion: devuelve el mismo periodo, no crea otro.
    again = await create_period(client, token)
    assert again["id"] == created["id"]

    listed = await client.get("/api/v1/tax/periods", headers=auth(token))
    assert listed.status_code == 200
    assert len([p for p in listed.json() if p["id"] == created["id"]]) == 1


async def test_periods_are_isolated_by_tenant(client) -> None:
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, TAX_SCOPES)

    period_a = await create_period(client, token_a, month=9)

    listed_b = await client.get("/api/v1/tax/periods", headers=auth(token_b))
    assert listed_b.status_code == 200
    assert all(item["id"] != period_a["id"] for item in listed_b.json())


async def test_same_file_is_not_duplicated(client, stored_objects) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    content = b"<factura>evidencia</factura>"

    first = await upload_evidence(client, token, filename="ventas.xml", content=content)
    assert first["duplicate"] is False
    assert first["fileType"] == "XML"
    assert first["sizeBytes"] == len(content)

    # Mismo contenido (aunque cambie el nombre): no se duplica la evidencia.
    second = await upload_evidence(client, token, filename="ventas-copia.xml", content=content)
    assert second["duplicate"] is True
    assert second["id"] == first["id"]

    listed = await client.get("/api/v1/tax/evidence", headers=auth(token))
    assert listed.status_code == 200
    assert len([item for item in listed.json() if item["sha256"] == first["sha256"]]) == 1


async def test_pdf_is_stored_as_evidence_only(client, stored_objects) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)

    record = await upload_evidence(
        client,
        token,
        filename="retencion.pdf",
        content=b"%PDF-1.4 retencion",
    )

    assert record["fileType"] == "PDF"
    # Regla del ADR 0012: los PDF no se leen automaticamente.
    assert record["processingNotes"] is not None
    assert "no se leen automaticamente" in record["processingNotes"]


async def test_evidence_can_be_linked_to_a_period(client, stored_objects) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    period = await create_period(client, token, month=8)

    record = await upload_evidence(
        client,
        token,
        filename="recibidos.txt",
        content=b"comprobantes recibidos",
        period_id=period["id"],
    )
    assert record["taxPeriodId"] == period["id"]

    filtered = await client.get(
        "/api/v1/tax/evidence",
        headers=auth(token),
        params={"taxPeriodId": period["id"]},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [record["id"]]


async def test_evidence_rejects_unknown_period(client, stored_objects) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)

    response = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, f"tax-evidence-{uuid.uuid4()}"),
        files={"file": ("x.xml", b"<a/>", "application/xml")},
        data={"taxPeriodId": str(uuid.uuid4())},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/tax/periods"),
        ("get", "/api/v1/tax/evidence"),
    ],
)
async def test_read_endpoints_require_tax_read_scope(client, method: str, path: str) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])
    response = await getattr(client, method)(path, headers=auth(token))
    assert response.status_code == 403


async def test_write_requires_tax_write_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:read"])
    response = await client.post(
        "/api/v1/tax/periods",
        headers=auth(token, f"tax-period-{uuid.uuid4()}"),
        json={"year": 2025, "month": 10, "obligationType": "IVA"},
    )
    assert response.status_code == 403

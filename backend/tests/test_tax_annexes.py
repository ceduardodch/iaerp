"""Flujo ATS desde evidencia fiscal, sin completar datos por suposicion."""

import uuid
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from app.services.tax import annexes as annexes_service
from app.services.tax import evidence as evidence_service
from app.services.tax import ingest as ingest_service

FIXTURES = Path(__file__).parent / "fixtures" / "sri"
TENANT_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def stored_annex_objects(monkeypatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}

    async def upload(*, object_key: str, data: bytes, **_kwargs):
        stored[object_key] = data
        return None

    async def download(*, object_key: str, **_kwargs) -> bytes:
        return stored[object_key]

    async def url(*, object_key: str, **_kwargs) -> str:
        return f"https://private.example/{object_key}"

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", upload)
    monkeypatch.setattr(ingest_service.storage, "download_artifact", download)
    monkeypatch.setattr(annexes_service.storage, "generate_presigned_download_url", url)
    return stored


async def _token(client) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": "a@iaerp.local",
            "tenantId": TENANT_ID,
            "scopes": ["tax:read", "tax:write"],
        },
    )
    return response.json()["accessToken"]


def _headers(token: str, prefix: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": f"{prefix}-{uuid.uuid4()}"}


async def _upload_and_ingest(client, token: str, filename: str) -> None:
    uploaded = await client.post(
        "/api/v1/tax/evidence",
        headers=_headers(token, "tax-evidence"),
        files={"file": (filename, (FIXTURES / filename).read_bytes(), "application/xml")},
    )
    assert uploaded.status_code == 201, uploaded.text
    ingested = await client.post(
        f"/api/v1/tax/evidence/{uploaded.json()['id']}/ingest",
        headers=_headers(token, "tax-ingest"),
    )
    assert ingested.status_code == 200, ingested.text


async def test_ats_is_built_from_period_evidence_and_zip_has_one_xml(
    client, stored_annex_objects
) -> None:
    token = await _token(client)
    await _upload_and_ingest(client, token, "factura_recibida_autorizada.xml")
    periods = await client.get("/api/v1/tax/periods", headers={"Authorization": f"Bearer {token}"})
    period = periods.json()[0]

    created = await client.post(
        f"/api/v1/tax/periods/{period['id']}/ats",
        headers=_headers(token, "tax-ats"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["annexType"] == "ATS"
    assert body["downloadUrl"].startswith("https://private.example/")

    zip_data = next(data for key, data in stored_annex_objects.items() if key.endswith(".zip"))
    archive = zipfile.ZipFile(BytesIO(zip_data))
    assert archive.namelist() == ["AT112025.xml"]
    assert b"276.30" in archive.read("AT112025.xml")


async def test_ats_refuses_unbacked_payment_method_and_keeps_the_gap_visible(
    client, stored_annex_objects
) -> None:
    token = await _token(client)
    await _upload_and_ingest(client, token, "factura_emitida_autorizada.xml")
    periods = await client.get("/api/v1/tax/periods", headers={"Authorization": f"Bearer {token}"})
    period = periods.json()[0]

    response = await client.post(
        f"/api/v1/tax/periods/{period['id']}/ats",
        headers=_headers(token, "tax-ats"),
    )
    assert response.status_code == 422
    assert "forma de pago respaldada" in response.json()["detail"]


async def test_sri_validation_issue_is_saved_per_private_annex(
    client, stored_annex_objects
) -> None:
    token = await _token(client)
    await _upload_and_ingest(client, token, "factura_recibida_autorizada.xml")
    periods = await client.get("/api/v1/tax/periods", headers={"Authorization": f"Bearer {token}"})
    annex = (
        await client.post(
            f"/api/v1/tax/periods/{periods.json()[0]['id']}/ats",
            headers=_headers(token, "tax-ats"),
        )
    ).json()

    created = await client.post(
        f"/api/v1/tax/annexes/{annex['id']}/issues",
        headers=_headers(token, "tax-issue"),
        json={"lineNumber": 12, "columnNumber": 7, "message": "Código no aceptado"},
    )
    assert created.status_code == 201, created.text
    listed = await client.get(
        f"/api/v1/tax/annexes/{annex['id']}/issues",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json()[0]["lineNumber"] == 12

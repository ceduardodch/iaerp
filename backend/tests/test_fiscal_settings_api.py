import uuid
from pathlib import Path

import pytest

from app.db.session import SessionFactory
from app.models.platform import TenantFiscalSettings
from app.services import fiscal_settings
from app.services.dev_certificate import generate_self_signed_p12

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


async def _token(client, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": "a@iaerp.local",
            "tenantId": str(TENANT_A),
            "scopes": scopes,
        },
    )
    assert response.status_code == 200
    return response.json()["accessToken"]


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}"}
    if key:
        result["Idempotency-Key"] = key
    return result


@pytest.mark.asyncio
async def test_fiscal_settings_are_tenant_scoped_and_password_is_encrypted(
    client,
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = await _token(client, ["organization:read", "organization:write"])
    certificate_path = generate_self_signed_p12(
        output_path=tmp_path / "tenant.p12",
        password=b"correct-password",
    )
    uploaded: dict[str, bytes] = {}

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs):
        uploaded[object_key] = data
        return None

    monkeypatch.setattr(fiscal_settings.storage, "upload_private_object", fake_upload)
    response = await client.post(
        "/api/v1/organization/signing-certificate",
        headers=_headers(token, "fiscal-certificate-upload-key"),
        files={"file": ("firma.p12", certificate_path.read_bytes(), "application/x-pkcs12")},
        data={"password": "correct-password"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["certificateConfigured"] is True
    assert len(body["certificateFingerprintSha256"]) == 64
    assert "password" not in response.text.lower()
    assert f"{TENANT_A}/fiscal/signing-certificate.p12" in uploaded

    async with SessionFactory() as session:
        entity = await session.get(TenantFiscalSettings, TENANT_A)
        assert entity is not None
        assert entity.certificate_password_encrypted != "correct-password"
        assert fiscal_settings.decrypt_secret(entity.certificate_password_encrypted or "") == (
            "correct-password"
        )


@pytest.mark.asyncio
async def test_upload_rejects_wrong_certificate_password(client, tmp_path: Path) -> None:
    token = await _token(client, ["organization:write"])
    certificate_path = generate_self_signed_p12(
        output_path=tmp_path / "tenant.p12",
        password=b"correct-password",
    )
    response = await client.post(
        "/api/v1/organization/signing-certificate",
        headers=_headers(token, "fiscal-certificate-invalid-key"),
        files={"file": ("firma.p12", certificate_path.read_bytes(), "application/x-pkcs12")},
        data={"password": "wrong-password"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid certificate or password"


@pytest.mark.asyncio
async def test_update_sri_environment_never_exposes_secret(client) -> None:
    token = await _token(client, ["organization:read", "organization:write"])
    response = await client.put(
        "/api/v1/organization/fiscal-settings",
        headers=_headers(token, "fiscal-environment-update-key"),
        json={"sriEnvironment": "2"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sriEnvironment": "2",
        "certificateConfigured": False,
        "certificateFingerprintSha256": None,
        "certificateSubject": None,
        "certificateValidFrom": None,
        "certificateValidTo": None,
        "certificateUploadedAt": None,
    }

    read = await client.get(
        "/api/v1/organization/fiscal-settings",
        headers=_headers(token),
    )
    assert read.status_code == 200
    assert read.json()["sriEnvironment"] == "2"


@pytest.mark.asyncio
async def test_fiscal_settings_require_correct_scopes(client) -> None:
    read_token = await _token(client, ["organization:read"])
    write_token = await _token(client, ["organization:write"])
    assert (
        await client.put(
            "/api/v1/organization/fiscal-settings",
            headers=_headers(read_token, "fiscal-denied-write-key"),
            json={"sriEnvironment": "1"},
        )
    ).status_code == 403
    assert (
        await client.get(
            "/api/v1/organization/fiscal-settings",
            headers=_headers(write_token),
        )
    ).status_code == 403

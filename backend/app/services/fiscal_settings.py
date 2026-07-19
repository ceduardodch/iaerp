from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.models.platform import TenantFiscalSettings
from app.schemas.platform import FiscalSettingsRead, FiscalSettingsUpdate
from app.services import storage

MAX_CERTIFICATE_SIZE = 2 * 1024 * 1024


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.IAERP_SECRETS_ENCRYPTION_KEY is not None:
        key = settings.IAERP_SECRETS_ENCRYPTION_KEY.get_secret_value().encode("ascii")
    elif settings.APP_ENV in {"development", "test"}:
        digest = hashlib.sha256(settings.DEV_JWT_SECRET.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    else:
        raise RuntimeError("IAERP_SECRETS_ENCRYPTION_KEY is required in shared environments")
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("IAERP_SECRETS_ENCRYPTION_KEY must be a valid Fernet key") from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Stored fiscal secret cannot be decrypted") from exc


async def get_or_create(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> TenantFiscalSettings:
    entity = await session.get(TenantFiscalSettings, tenant_id)
    if entity is None:
        entity = TenantFiscalSettings(tenant_id=tenant_id, sri_environment="1")
        session.add(entity)
        await session.flush()
    return entity


def to_read(entity: TenantFiscalSettings) -> FiscalSettingsRead:
    return FiscalSettingsRead(
        sri_environment=entity.sri_environment,
        certificate_configured=bool(
            entity.certificate_object_key and entity.certificate_password_encrypted
        ),
        certificate_fingerprint_sha256=entity.certificate_fingerprint_sha256,
        certificate_subject=entity.certificate_subject,
        certificate_valid_from=entity.certificate_valid_from,
        certificate_valid_to=entity.certificate_valid_to,
        certificate_uploaded_at=entity.certificate_uploaded_at,
    )


async def read_settings(
    session: AsyncSession,
    context: AuthContext,
) -> FiscalSettingsRead:
    return to_read(await get_or_create(session, context.tenant_id))


async def update_settings(
    session: AsyncSession,
    context: AuthContext,
    data: FiscalSettingsUpdate,
) -> FiscalSettingsRead:
    entity = await get_or_create(session, context.tenant_id)
    entity.sri_environment = data.sri_environment
    await session.flush()
    return to_read(entity)


async def upload_signing_certificate(
    session: AsyncSession,
    context: AuthContext,
    *,
    filename: str | None,
    data: bytes,
    password: str,
) -> FiscalSettingsRead:
    if not filename or not filename.lower().endswith((".p12", ".pfx")):
        raise HTTPException(status_code=422, detail="Certificate must be a .p12 or .pfx file")
    if not data or len(data) > MAX_CERTIFICATE_SIZE:
        raise HTTPException(status_code=422, detail="Certificate must be between 1 byte and 2 MB")
    if not password:
        raise HTTPException(status_code=422, detail="Certificate password is required")

    try:
        private_key, certificate, _chain = pkcs12.load_key_and_certificates(
            data,
            password.encode("utf-8"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid certificate or password") from exc
    if private_key is None or certificate is None:
        raise HTTPException(status_code=422, detail="Certificate must include a private key")

    now = datetime.now(UTC)
    valid_from = certificate.not_valid_before_utc
    valid_to = certificate.not_valid_after_utc
    if valid_to <= now:
        raise HTTPException(status_code=422, detail="Certificate has expired")
    if valid_from > now:
        raise HTTPException(status_code=422, detail="Certificate is not valid yet")

    fingerprint = hashlib.sha256(certificate.public_bytes(Encoding.DER)).hexdigest().upper()
    object_key = f"{context.tenant_id}/fiscal/signing-certificate.p12"
    await storage.upload_private_object(object_key=object_key, data=data)

    entity = await get_or_create(session, context.tenant_id)
    entity.certificate_object_key = object_key
    entity.certificate_password_encrypted = encrypt_secret(password)
    entity.certificate_fingerprint_sha256 = fingerprint
    entity.certificate_subject = certificate.subject.rfc4514_string()
    entity.certificate_valid_from = valid_from
    entity.certificate_valid_to = valid_to
    entity.certificate_uploaded_at = now
    await session.flush()
    return to_read(entity)


async def load_tenant_signing_credentials(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> tuple[bytes, bytes, TenantFiscalSettings]:
    entity = await session.get(TenantFiscalSettings, tenant_id)
    if (
        entity is None
        or not entity.certificate_object_key
        or not entity.certificate_password_encrypted
    ):
        raise HTTPException(status_code=409, detail="Signing certificate is not configured")
    certificate_bytes = await storage.download_artifact(object_key=entity.certificate_object_key)
    password = decrypt_secret(entity.certificate_password_encrypted).encode("utf-8")
    return certificate_bytes, password, entity


__all__ = [
    "decrypt_secret",
    "encrypt_secret",
    "load_tenant_signing_credentials",
    "read_settings",
    "to_read",
    "update_settings",
    "upload_signing_certificate",
]

"""Pruebas de almacenamiento privado contra un MinIO real (ADR 0005).

Se ejecutan en vivo contra ``localhost:9000`` (el stack de este entorno lo
provee) usando un bucket de prueba dedicado (``iaerp-documents-test``, nunca
el bucket real ``iaerp-documents``) que se limpia al finalizar el modulo. Si
MinIO no responde, las pruebas se saltan explicitamente en vez de fallar,
para no romper la suite en un entorno sin el servicio disponible.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Iterator

import httpx
import pytest

from app.services.storage import (
    generate_presigned_download_url,
    object_exists,
    upload_artifact,
)

_TEST_BUCKET = "iaerp-documents-test"
_MINIO_HOST = "localhost"
_MINIO_PORT = 9000


def _minio_is_reachable() -> bool:
    try:
        with socket.create_connection((_MINIO_HOST, _MINIO_PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _minio_is_reachable(),
    reason="MinIO is not reachable at localhost:9000 in this environment",
)


@pytest.fixture(autouse=True)
def _cleanup_test_bucket() -> Iterator[None]:
    yield
    from minio import Minio

    from app.core.config import get_settings

    settings = get_settings()
    client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=settings.MINIO_SECURE,
    )
    if client.bucket_exists(_TEST_BUCKET):
        for obj in client.list_objects(_TEST_BUCKET, recursive=True):
            if obj.object_name:
                client.remove_object(_TEST_BUCKET, obj.object_name)
        client.remove_bucket(_TEST_BUCKET)


async def test_upload_creates_bucket_idempotently_and_verifies_checksum() -> None:
    tenant_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    payload = b"<factura>contenido de prueba</factura>"

    result = await upload_artifact(
        tenant_id=tenant_id,
        document_id=document_id,
        artifact_type="xml-signed",
        version=1,
        data=payload,
        bucket_name=_TEST_BUCKET,
    )

    assert result.object_key == (
        f"{tenant_id}/sales-documents/{document_id}/xml-signed-v1.xml"
    )
    assert result.size_bytes == len(payload)

    import hashlib

    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert await object_exists(object_key=result.object_key, bucket_name=_TEST_BUCKET)

    # Uploading again (e.g. bucket already exists) must not fail: bucket
    # creation is idempotent.
    second_result = await upload_artifact(
        tenant_id=tenant_id,
        document_id=document_id,
        artifact_type="ride-pdf",
        version=1,
        data=b"%PDF-1.4 fake pdf bytes",
        bucket_name=_TEST_BUCKET,
    )
    assert second_result.object_key.endswith("ride-pdf-v1.pdf")


async def test_presigned_url_allows_download_but_anonymous_get_fails() -> None:
    tenant_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    payload = b"<factura>contenido descargable</factura>"

    result = await upload_artifact(
        tenant_id=tenant_id,
        document_id=document_id,
        artifact_type="xml-signed",
        version=1,
        data=payload,
        bucket_name=_TEST_BUCKET,
    )

    presigned_url = await generate_presigned_download_url(
        object_key=result.object_key,
        bucket_name=_TEST_BUCKET,
    )

    async with httpx.AsyncClient() as client:
        presigned_response = await client.get(presigned_url)
        assert presigned_response.status_code == 200
        assert presigned_response.content == payload

        anonymous_url = f"http://{_MINIO_HOST}:{_MINIO_PORT}/{_TEST_BUCKET}/{result.object_key}"
        anonymous_response = await client.get(anonymous_url)
        assert anonymous_response.status_code in (403, 404)


async def test_object_exists_returns_false_for_missing_key() -> None:
    assert not await object_exists(
        object_key="nonexistent/does-not-exist.xml",
        bucket_name=_TEST_BUCKET,
    )

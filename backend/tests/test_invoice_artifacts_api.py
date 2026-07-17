"""Pruebas de los endpoints de artefactos de factura (listar y descargar).

``GET /invoices/{id}/artifacts`` y su descarga prefirmada son la unica via de
acceso a XML firmado/RIDE PDF (ADR 0005): nunca una URL publica. Estas
pruebas insertan un ``DocumentArtifact`` directamente en base de datos (la
fase de emision que los crea de verdad es Fase 4) para validar scope,
aislamiento de tenant y que la URL de descarga se genera solo tras pasar por
el endpoint autenticado.
"""

import socket
import uuid

import pytest

from app.db.session import SessionFactory
from app.models.billing import DocumentArtifact
from tests.test_billing_api import (
    TENANT_A,
    TENANT_B,
    _invoice_payload,
    _setup_billing_masters,
    auth,
    token_for,
)


def _minio_is_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 9000), timeout=1):
            return True
    except OSError:
        return False


_EMAIL_BY_TENANT = {TENANT_A: "a@iaerp.local", TENANT_B: "b@iaerp.local"}


async def _create_draft_invoice(client, key_prefix: str, tenant_id: uuid.UUID) -> tuple[str, str]:
    email = _EMAIL_BY_TENANT[tenant_id]
    token = await token_for(
        client,
        email,
        tenant_id,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix=key_prefix)
    token_invoices = await token_for(
        client, email, tenant_id, ["invoices:write", "invoices:read"]
    )
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, f"{key_prefix}-invoice-0001"),
        json=_invoice_payload(masters),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], token_invoices


async def _insert_artifact(
    *, tenant_id: uuid.UUID, document_id: uuid.UUID, object_key: str
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        artifact = DocumentArtifact(
            tenant_id=tenant_id,
            sales_document_id=document_id,
            artifact_type="xml-signed",
            object_key=object_key,
            sha256="a" * 64,
            version=1,
        )
        session.add(artifact)
        await session.flush()
        artifact_id = artifact.id
    return artifact_id


async def test_list_artifacts_requires_read_scope(client) -> None:
    invoice_id, _ = await _create_draft_invoice(client, "art-scope", TENANT_A)
    token_no_scope = await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])
    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts",
        headers=auth(token_no_scope),
    )
    assert response.status_code == 403


async def test_list_artifacts_empty_for_draft_invoice(client) -> None:
    invoice_id, token = await _create_draft_invoice(client, "art-empty", TENANT_A)
    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts",
        headers=auth(token),
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_list_artifacts_returns_inserted_rows(client) -> None:
    invoice_id, token = await _create_draft_invoice(client, "art-list", TENANT_A)
    await _insert_artifact(
        tenant_id=TENANT_A,
        document_id=uuid.UUID(invoice_id),
        object_key=f"{TENANT_A}/sales-documents/{invoice_id}/xml-signed-v1.xml",
    )

    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts",
        headers=auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["artifactType"] == "xml-signed"
    assert body[0]["sha256"] == "a" * 64
    assert body[0]["version"] == 1
    assert "downloadUrl" not in body[0]


async def test_list_artifacts_is_tenant_isolated(client) -> None:
    invoice_id, _ = await _create_draft_invoice(client, "art-tenant-a", TENANT_A)
    await _insert_artifact(
        tenant_id=TENANT_A,
        document_id=uuid.UUID(invoice_id),
        object_key=f"{TENANT_A}/sales-documents/{invoice_id}/xml-signed-v1.xml",
    )

    token_b = await token_for(client, "b@iaerp.local", TENANT_B, ["invoices:read"])
    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts",
        headers=auth(token_b),
    )
    assert response.status_code == 404


async def test_download_unknown_artifact_returns_404(client) -> None:
    invoice_id, token = await _create_draft_invoice(client, "art-404", TENANT_A)
    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts/{uuid.uuid4()}/download",
        headers=auth(token),
    )
    assert response.status_code == 404


@pytest.mark.skipif(
    not _minio_is_reachable(),
    reason="MinIO is not reachable at localhost:9000 in this environment",
)
async def test_download_artifact_endpoint_returns_working_presigned_url(client) -> None:
    """End-to-end: endpoint -> service -> MinIO presigned URL -> real download.

    Uploads the artifact to the tenant's REAL configured bucket
    (``MINIO_DOCUMENTS_BUCKET``, default ``iaerp-documents``) so the endpoint
    (which always targets that bucket) returns a URL that actually serves the
    uploaded bytes. Cleans up only the object it created, never the bucket
    itself (Fase 4 and other tests may rely on it existing).
    """
    from app.core.config import get_settings
    from app.services import storage

    settings = get_settings()
    invoice_id, token = await _create_draft_invoice(client, "art-download", TENANT_A)
    payload = b"<factura>contenido firmado de prueba</factura>"

    upload_result = await storage.upload_artifact(
        tenant_id=str(TENANT_A),
        document_id=invoice_id,
        artifact_type="xml-signed",
        version=1,
        data=payload,
    )
    artifact_id = await _insert_artifact(
        tenant_id=TENANT_A,
        document_id=uuid.UUID(invoice_id),
        object_key=upload_result.object_key,
    )

    response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts/{artifact_id}/download",
        headers=auth(token),
    )
    assert response.status_code == 200
    download_url = response.json()["downloadUrl"]
    assert download_url.startswith("http")
    assert response.json()["expiresInSeconds"] > 0

    import httpx

    async with httpx.AsyncClient() as http_client:
        download_response = await http_client.get(download_url)
        assert download_response.status_code == 200
        assert download_response.content == payload

        anonymous_url = (
            f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_DOCUMENTS_BUCKET}/"
            f"{upload_result.object_key}"
        )
        anonymous_response = await http_client.get(anonymous_url)
        assert anonymous_response.status_code in (403, 404)

    from minio import Minio

    cleanup_client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=settings.MINIO_SECURE,
    )
    cleanup_client.remove_object(settings.MINIO_DOCUMENTS_BUCKET, upload_result.object_key)

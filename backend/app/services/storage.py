"""Cliente de almacenamiento privado (MinIO/S3) para artefactos de facturacion.

ADR 0005: XML firmado y RIDE PDF son sensibles y viven en un bucket privado,
nunca en el filesystem del contenedor. El SDK oficial de MinIO es sincrono;
en vez de mantener un cliente async paralelo, cada llamada bloqueante se
ejecuta con ``asyncio.to_thread`` para no bloquear el loop de eventos de
FastAPI, siguiendo el mismo principio (no reinventar un cliente async) que ya
aplica el resto del backend con librerias sincronas puntuales.

El bucket es privado por defecto (MinIO no aplica una politica publica salvo
que se configure explicitamente, y aqui nunca se configura una). Toda
descarga pasa por una URL prefirmada de corta duracion generada solo despues
de que el endpoint REST valida el scope ``invoices:read`` del llamador (ver
``api/router.py``); nunca se expone una URL publica ni permanente.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings

# Duracion corta a proposito: una URL prefirmada filtrada solo debe ser util
# por una ventana breve, no como enlace permanente sustituto de autenticacion.
PRESIGNED_URL_EXPIRY = timedelta(minutes=5)

_ARTIFACT_EXTENSION_BY_TYPE = {
    "xml-signed": "xml",
    "ride-pdf": "pdf",
}


@dataclass(frozen=True)
class UploadResult:
    """Resultado de subir un artefacto: clave del objeto y checksum verificado."""

    object_key: str
    sha256: str
    size_bytes: int


def object_key_for_artifact(
    *,
    tenant_id: str,
    document_id: str,
    artifact_type: str,
    version: int,
) -> str:
    """Construye la clave de objeto segun el layout de ADR 0008/sprint-02.md.

    ``{tenant_id}/sales-documents/{document_id}/{artifact_type}-v{version}.{ext}``
    """

    if artifact_type not in _ARTIFACT_EXTENSION_BY_TYPE:
        raise ValueError(f"Unsupported artifact type: {artifact_type!r}")
    extension = _ARTIFACT_EXTENSION_BY_TYPE[artifact_type]
    return f"{tenant_id}/sales-documents/{document_id}/{artifact_type}-v{version}.{extension}"


def _content_type_for_artifact(artifact_type: str) -> str:
    return "application/xml" if artifact_type == "xml-signed" else "application/pdf"


@lru_cache
def _client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=settings.MINIO_SECURE,
    )


@lru_cache
def _public_client() -> Minio:
    """Cliente usado solo para firmar URL de descarga.

    La firma prefirmada incluye el host del endpoint; debe ser el host
    alcanzable por quien recibe la URL (el navegador), no el host interno de
    la red de contenedores. Si no se configura un endpoint publico, coincide
    con el interno.
    """

    settings = get_settings()
    endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
    # region explicita: al firmar una URL con un endpoint publico que puede no
    # ser alcanzable desde este proceso (p. ej. `localhost:9000` visto desde el
    # contenedor), el SDK no debe intentar resolver la region por red. Fijarla
    # evita ese round-trip y mantiene la firma puramente local.
    return Minio(
        endpoint,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
        secure=settings.MINIO_SECURE,
        region=settings.MINIO_REGION,
    )


def _ensure_bucket_sync(client: Minio, bucket_name: str) -> None:
    """Crea el bucket si no existe. Idempotente: no falla si ya existe.

    No se aplica ninguna politica publica: el bucket permanece privado por
    defecto, unicamente accesible con las credenciales del backend o via URL
    prefirmada de corta duracion.
    """

    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)


def _upload_sync(
    client: Minio,
    *,
    bucket_name: str,
    object_key: str,
    data: bytes,
    content_type: str,
) -> UploadResult:
    _ensure_bucket_sync(client, bucket_name)
    checksum = hashlib.sha256(data).hexdigest()
    client.put_object(
        bucket_name,
        object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )

    # Verifica el checksum leyendo de vuelta el objeto recien subido: protege
    # contra corrupcion silenciosa en transito (ADR 0008/sprint-02.md exige
    # checksum verificado al subir, no solo calculado localmente).
    response = client.get_object(bucket_name, object_key)
    try:
        downloaded = response.read()
    finally:
        response.close()
        response.release_conn()
    downloaded_checksum = hashlib.sha256(downloaded).hexdigest()
    if downloaded_checksum != checksum:
        raise ValueError(
            f"Checksum mismatch after upload for {object_key!r}: "
            f"expected {checksum}, got {downloaded_checksum}"
        )

    return UploadResult(object_key=object_key, sha256=checksum, size_bytes=len(data))


async def upload_artifact(
    *,
    tenant_id: str,
    document_id: str,
    artifact_type: str,
    version: int,
    data: bytes,
    bucket_name: str | None = None,
) -> UploadResult:
    """Sube un artefacto (XML firmado o RIDE PDF) y verifica su checksum SHA-256.

    Crea el bucket de forma idempotente si todavia no existe (verificado: no
    existe hoy en el stack de este entorno). No decide donde se registra el
    ``DocumentArtifact`` en base de datos; eso es responsabilidad del
    llamador (fase 4), que recibe el ``UploadResult`` y lo persiste.
    """

    settings = get_settings()
    resolved_bucket = bucket_name or settings.MINIO_DOCUMENTS_BUCKET
    object_key = object_key_for_artifact(
        tenant_id=tenant_id,
        document_id=document_id,
        artifact_type=artifact_type,
        version=version,
    )
    client = _client()
    return await asyncio.to_thread(
        _upload_sync,
        client,
        bucket_name=resolved_bucket,
        object_key=object_key,
        data=data,
        content_type=_content_type_for_artifact(artifact_type),
    )


async def upload_private_object(
    *,
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    bucket_name: str | None = None,
) -> UploadResult:
    """Store tenant-scoped configuration bytes in the existing private bucket."""

    settings = get_settings()
    resolved_bucket = bucket_name or settings.MINIO_DOCUMENTS_BUCKET
    return await asyncio.to_thread(
        _upload_sync,
        _client(),
        bucket_name=resolved_bucket,
        object_key=object_key,
        data=data,
        content_type=content_type,
    )


def _presigned_download_url_sync(
    client: Minio,
    *,
    bucket_name: str,
    object_key: str,
    expiry: timedelta,
    file_name: str | None,
    content_type: str | None,
) -> str:
    response_headers: dict[str, str | list[str] | tuple[str]] | None = None
    if file_name and content_type:
        response_headers = {
            "response-content-disposition": f'attachment; filename="{file_name}"',
            "response-content-type": content_type,
        }
    return client.presigned_get_object(
        bucket_name,
        object_key,
        expires=expiry,
        response_headers=response_headers,
    )


async def generate_presigned_download_url(
    *,
    object_key: str,
    bucket_name: str | None = None,
    expiry: timedelta = PRESIGNED_URL_EXPIRY,
    file_name: str | None = None,
    content_type: str | None = None,
) -> str:
    """Genera una URL prefirmada de corta duracion para descargar un objeto.

    El llamador (endpoint REST) debe validar autorizacion ANTES de invocar
    esta funcion: esta funcion no repite ninguna verificacion de scope o
    tenant, solo genera la URL firmada por MinIO.
    """

    settings = get_settings()
    resolved_bucket = bucket_name or settings.MINIO_DOCUMENTS_BUCKET
    client = _public_client()
    return await asyncio.to_thread(
        _presigned_download_url_sync,
        client,
        bucket_name=resolved_bucket,
        object_key=object_key,
        expiry=expiry,
        file_name=file_name,
        content_type=content_type,
    )


def _download_sync(client: Minio, *, bucket_name: str, object_key: str) -> bytes:
    response = client.get_object(bucket_name, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def download_artifact(*, object_key: str, bucket_name: str | None = None) -> bytes:
    """Descarga el contenido crudo de un artefacto ya subido.

    Usado por ``workers/sri_transmission.py`` para recuperar el XML firmado
    antes de transmitirlo; no valida autorizacion (eso ya lo hizo el
    llamador al resolver el ``DocumentArtifact`` tenant-scoped).
    """

    settings = get_settings()
    resolved_bucket = bucket_name or settings.MINIO_DOCUMENTS_BUCKET
    client = _client()
    return await asyncio.to_thread(
        _download_sync,
        client,
        bucket_name=resolved_bucket,
        object_key=object_key,
    )


async def object_exists(*, object_key: str, bucket_name: str | None = None) -> bool:
    """Verifica si un objeto existe en el bucket (usado en pruebas y diagnostico)."""

    settings = get_settings()
    resolved_bucket = bucket_name or settings.MINIO_DOCUMENTS_BUCKET
    client = _client()

    def _check() -> bool:
        try:
            client.stat_object(resolved_bucket, object_key)
            return True
        except S3Error as error:
            if error.code == "NoSuchKey":
                return False
            raise

    return await asyncio.to_thread(_check)


__all__ = [
    "PRESIGNED_URL_EXPIRY",
    "UploadResult",
    "download_artifact",
    "generate_presigned_download_url",
    "object_exists",
    "object_key_for_artifact",
    "upload_artifact",
    "upload_private_object",
]

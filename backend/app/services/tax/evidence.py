"""Carga y custodia de evidencia tributaria (ADR 0012).

El archivo original es la fuente de verdad: se guarda tal cual en MinIO y se
identifica por su ``sha256``. Volver a subir el mismo archivo NO duplica
evidencia ni recalcula nada; se devuelve el registro existente marcado como
duplicado, para que la carga sea repetible sin ensuciar el periodo.

Este modulo no interpreta el contenido: clasificar el archivo y crear los
``FiscalDocument`` es responsabilidad de la ingesta (etapa E2).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import TaxEvidence, TaxPeriod
from app.services import storage

# 25 MB: un ZIP mensual de comprobantes recibidos cabe holgadamente.
MAX_EVIDENCE_SIZE = 25 * 1024 * 1024

_EXTENSION_TO_TYPE = {
    ".xml": "XML",
    ".txt": "TXT",
    ".csv": "TXT",
    ".pdf": "PDF",
    ".zip": "ZIP",
}

_CONTENT_TYPES = {
    "XML": "application/xml",
    "TXT": "text/plain",
    "PDF": "application/pdf",
    "ZIP": "application/zip",
    "OTHER": "application/octet-stream",
}


def classify_file_type(filename: str) -> str:
    """Tipo de archivo por extension; ``OTHER`` si no se reconoce."""
    lowered = (filename or "").lower()
    for extension, file_type in _EXTENSION_TO_TYPE.items():
        if lowered.endswith(extension):
            return file_type
    return "OTHER"


def evidence_object_key(
    *,
    tenant_id: uuid.UUID,
    sha256: str,
    filename: str,
) -> str:
    """Ruta en MinIO: por tenant y hash, para que sea estable e idempotente."""
    safe_name = filename.replace("/", "_").replace("\\", "_")[-120:]
    return f"{tenant_id}/tax/evidence/{sha256}/{safe_name}"


async def upload_evidence(
    session: AsyncSession,
    context: AuthContext,
    *,
    filename: str | None,
    data: bytes,
    origin: str = "MANUAL",
    tax_period_id: uuid.UUID | None = None,
) -> tuple[TaxEvidence, bool]:
    """Guarda un archivo de evidencia. Devuelve ``(registro, es_duplicado)``.

    No se infiere el periodo aqui: si el llamador no lo indica, queda en ``None``
    hasta que la ingesta lea la fecha real de emision del comprobante.
    """
    if not filename:
        raise HTTPException(status_code=422, detail="Evidence file must have a filename")
    if not data:
        raise HTTPException(status_code=422, detail="Evidence file is empty")
    if len(data) > MAX_EVIDENCE_SIZE:
        raise HTTPException(status_code=422, detail="Evidence file exceeds 25 MB")

    sha256 = hashlib.sha256(data).hexdigest()

    existing = await session.scalar(
        select(TaxEvidence).where(
            TaxEvidence.tenant_id == context.tenant_id,
            TaxEvidence.sha256 == sha256,
        )
    )
    if existing is not None:
        # Mismo archivo ya cargado: no se vuelve a subir ni se altera el estado.
        return existing, True

    if tax_period_id is not None:
        period = await session.scalar(
            select(TaxPeriod).where(
                TaxPeriod.tenant_id == context.tenant_id,
                TaxPeriod.id == tax_period_id,
            )
        )
        if period is None:
            raise HTTPException(status_code=404, detail="Tax period not found")

    file_type = classify_file_type(filename)
    object_key = evidence_object_key(
        tenant_id=context.tenant_id,
        sha256=sha256,
        filename=filename,
    )
    await storage.upload_private_object(
        object_key=object_key,
        data=data,
        content_type=_CONTENT_TYPES.get(file_type, _CONTENT_TYPES["OTHER"]),
    )

    evidence = TaxEvidence(
        tenant_id=context.tenant_id,
        tax_period_id=tax_period_id,
        filename=filename[-255:],
        file_type=file_type,
        object_key=object_key,
        sha256=sha256,
        size_bytes=len(data),
        origin=origin,
        uploaded_at=datetime.now(UTC),
        processing_notes=(
            None
            if file_type in {"XML", "TXT", "ZIP"}
            else "Archivo guardado como evidencia; sus valores no se leen automaticamente."
        ),
    )
    session.add(evidence)
    await session.flush()
    return evidence, False


async def list_evidence(
    session: AsyncSession,
    context: AuthContext,
    *,
    tax_period_id: uuid.UUID | None = None,
) -> list[TaxEvidence]:
    query = select(TaxEvidence).where(TaxEvidence.tenant_id == context.tenant_id)
    if tax_period_id is not None:
        query = query.where(TaxEvidence.tax_period_id == tax_period_id)
    result = await session.scalars(query.order_by(TaxEvidence.uploaded_at.desc()))
    return list(result)


async def download_url(
    session: AsyncSession,
    context: AuthContext,
    *,
    evidence_id: uuid.UUID,
) -> str:
    """URL temporal para descargar el archivo original (bucket privado)."""
    evidence = await session.scalar(
        select(TaxEvidence).where(
            TaxEvidence.tenant_id == context.tenant_id,
            TaxEvidence.id == evidence_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return await storage.generate_presigned_download_url(object_key=evidence.object_key)


__all__ = [
    "MAX_EVIDENCE_SIZE",
    "classify_file_type",
    "download_url",
    "evidence_object_key",
    "list_evidence",
    "upload_evidence",
]

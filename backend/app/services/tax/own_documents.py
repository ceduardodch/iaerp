"""Importa al modulo tributario los comprobantes que la propia entidad emitio.

Las ventas del periodo no pueden depender de que el usuario descargue y suba sus
propios comprobantes: IAERP ya los emite, los firma y guarda el XML como
artefacto ``xml-signed``, con la autorizacion del SRI en ``SRITransmission``.

Este modulo los trae al modulo tributario respetando el ADR 0012:

- **Solo comprobantes AUTORIZADOS.** Un borrador o un rechazado no es evidencia
  para declarar.
- **La fuente es el XML firmado**, no los campos internos: se parsea el mismo
  archivo que se envio al SRI, para que el detalle declarado coincida con el
  comprobante real.
- Sin autorizacion registrada, el comprobante se omite y se reporta el faltante;
  no se inventa un numero de autorizacion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import DocumentArtifact, SalesDocument, SRITransmission
from app.models.tax import TaxPeriod
from app.services import storage
from app.services.tax.ingest import upsert_parsed_document
from app.services.tax.sri_xml import parse_signed_receipt


@dataclass
class OwnDocumentsResult:
    """Resumen de la importacion, sin ocultar lo que quedo fuera."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)


async def _signed_xml(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> bytes | None:
    artifact = await session.scalar(
        select(DocumentArtifact)
        .where(
            DocumentArtifact.tenant_id == tenant_id,
            DocumentArtifact.sales_document_id == document_id,
            DocumentArtifact.artifact_type == "xml-signed",
        )
        .order_by(DocumentArtifact.version.desc())
        .limit(1)
    )
    if artifact is None:
        return None
    return await storage.download_artifact(object_key=artifact.object_key)


async def import_issued_documents(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
    tenant_ruc: str,
) -> OwnDocumentsResult:
    """Trae al periodo los comprobantes autorizados que emitio la entidad."""
    result = OwnDocumentsResult()

    documents = list(
        await session.scalars(
            select(SalesDocument).where(
                SalesDocument.tenant_id == context.tenant_id,
                SalesDocument.status == "AUTHORIZED",
            )
        )
    )

    missing_xml: list[str] = []
    missing_authorization: list[str] = []

    for document in documents:
        # El periodo se decide por la fecha de emision del comprobante, igual
        # que con la evidencia descargada.
        if document.issue_date.year != period.year or document.issue_date.month != period.month:
            continue

        transmission = await session.scalar(
            select(SRITransmission)
            .where(
                SRITransmission.tenant_id == context.tenant_id,
                SRITransmission.sales_document_id == document.id,
                SRITransmission.authorization_number.is_not(None),
            )
            .order_by(SRITransmission.created_at.desc())
            .limit(1)
        )
        if transmission is None or not transmission.authorization_number:
            missing_authorization.append(document.sequential)
            result.skipped += 1
            continue

        xml_bytes = await _signed_xml(
            session,
            tenant_id=context.tenant_id,
            document_id=document.id,
        )
        if xml_bytes is None:
            missing_xml.append(document.sequential)
            result.skipped += 1
            continue

        parsed = parse_signed_receipt(
            xml_bytes,
            authorization_number=transmission.authorization_number,
            authorized_at=transmission.authorized_at,
        )
        _fiscal_document, created = await upsert_parsed_document(
            session,
            context,
            parsed=parsed,
            tenant_ruc=tenant_ruc,
            evidence_id=None,
            sales_document_id=document.id,
        )
        if created:
            result.created += 1
        else:
            result.updated += 1

    if missing_authorization:
        result.notes.append(
            "Sin autorizacion registrada (no se importaron): "
            + ", ".join(sorted(missing_authorization))
        )
    if missing_xml:
        result.notes.append(
            "Sin XML firmado disponible (no se importaron): " + ", ".join(sorted(missing_xml))
        )
    if not documents:
        result.notes.append(
            "No hay comprobantes propios autorizados; las ventas del periodo saldran "
            "solo de la evidencia que cargues."
        )

    return result


__all__ = ["OwnDocumentsResult", "import_issued_documents"]

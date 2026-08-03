"""Generacion y custodia privada de anexos tributarios."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import Tenant
from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxAnnex, TaxPeriod
from app.services import storage
from app.services.tax.ats import ats_filename, build_ats_xml, build_ats_zip
from app.services.tax.ats_builder import build_ats_input


def _object_key(*, tenant_id: uuid.UUID, period_id: uuid.UUID, version: int, filename: str) -> str:
    return f"{tenant_id}/tax/annexes/{period_id}/ATS/v{version}/{filename}"


async def generate_ats(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
) -> TaxAnnex:
    """Genera un ATS solo si cada dato exigido tiene evidencia."""
    tenant = await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    documents = list(
        await session.scalars(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.tax_period_id == period.id,
            )
        )
    )
    document_ids = [document.id for document in documents]
    taxes: list[FiscalDocumentTax] = []
    retentions: list[FiscalRetention] = []
    if document_ids:
        taxes = list(
            await session.scalars(
                select(FiscalDocumentTax).where(
                    FiscalDocumentTax.tenant_id == context.tenant_id,
                    FiscalDocumentTax.fiscal_document_id.in_(document_ids),
                )
            )
        )
        retentions = list(
            await session.scalars(
                select(FiscalRetention).where(
                    FiscalRetention.tenant_id == context.tenant_id,
                    FiscalRetention.fiscal_document_id.in_(document_ids),
                )
            )
        )
    result = build_ats_input(
        period=period,
        identification=tenant.ruc,
        legal_name=tenant.name,
        documents=documents,
        taxes=taxes,
        retentions=retentions,
    )
    if result.missing:
        raise HTTPException(
            status_code=422,
            detail="No se puede generar ATS con datos sin respaldo: " + " ".join(result.missing),
        )

    version = (
        await session.scalar(
            select(func.max(TaxAnnex.version)).where(
                TaxAnnex.tenant_id == context.tenant_id,
                TaxAnnex.tax_period_id == period.id,
                TaxAnnex.annex_type == "ATS",
            )
        )
        or 0
    ) + 1
    filename = ats_filename(result.data)
    xml_bytes = build_ats_xml(result.data)
    zip_bytes = build_ats_zip(xml_bytes, filename=filename)
    xml_key = _object_key(
        tenant_id=context.tenant_id,
        period_id=period.id,
        version=version,
        filename=filename,
    )
    zip_key = _object_key(
        tenant_id=context.tenant_id,
        period_id=period.id,
        version=version,
        filename=filename.replace(".xml", ".zip"),
    )
    await storage.upload_private_object(
        object_key=xml_key, data=xml_bytes, content_type="application/xml"
    )
    await storage.upload_private_object(
        object_key=zip_key, data=zip_bytes, content_type="application/zip"
    )
    annex = TaxAnnex(
        tenant_id=context.tenant_id,
        tax_period_id=period.id,
        annex_type="ATS",
        xml_object_key=xml_key,
        zip_object_key=zip_key,
        xml_sha256=hashlib.sha256(xml_bytes).hexdigest(),
        version=version,
    )
    session.add(annex)
    await session.flush()
    return annex


async def download_url(
    session: AsyncSession,
    context: AuthContext,
    *,
    annex_id: uuid.UUID,
) -> str:
    annex = await session.scalar(
        select(TaxAnnex).where(TaxAnnex.tenant_id == context.tenant_id, TaxAnnex.id == annex_id)
    )
    if annex is None or not annex.zip_object_key:
        raise HTTPException(status_code=404, detail="Tax annex not found")
    return await storage.generate_presigned_download_url(
        object_key=annex.zip_object_key,
        file_name=f"ATS-v{annex.version}.zip",
        content_type="application/zip",
    )


__all__ = ["download_url", "generate_ats"]

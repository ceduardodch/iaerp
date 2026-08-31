"""Crea y consulta trabajos para completar XML recibidos desde el SRI."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument, TaxPeriod, TaxXmlRecoveryItem, TaxXmlRecoveryJob
from app.services import access_key as access_key_service

RECOVERY_REQUESTED_EVENT = "tax.xml_recovery.requested"


def job_read_payload(
    job: TaxXmlRecoveryJob,
    *,
    items: Sequence[TaxXmlRecoveryItem],
) -> dict[str, object]:
    """Expone solo los campos públicos del trabajo y descarta metadatos ORM."""
    return {
        "id": job.id,
        "tax_period_id": job.tax_period_id,
        "status": job.status,
        "total_count": job.total_count,
        "processed_count": job.processed_count,
        "recovered_count": job.recovered_count,
        "unavailable_count": job.unavailable_count,
        "failed_count": job.failed_count,
        "items": list(items),
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


async def create_job(
    session: AsyncSession,
    context: AuthContext,
    *,
    period_id: uuid.UUID,
    reuse_active: bool = False,
) -> TaxXmlRecoveryJob:
    period = await session.scalar(
        select(TaxPeriod)
        .where(
            TaxPeriod.tenant_id == context.tenant_id,
            TaxPeriod.id == period_id,
            TaxPeriod.obligation_type == "IVA",
        )
        .with_for_update()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Tax period not found")
    if period.status == "DECLARADO":
        raise HTTPException(status_code=409, detail="Declared periods cannot recover XML")

    active = await session.scalar(
        select(TaxXmlRecoveryJob)
        .where(
            TaxXmlRecoveryJob.tenant_id == context.tenant_id,
            TaxXmlRecoveryJob.tax_period_id == period_id,
            TaxXmlRecoveryJob.status.in_(("QUEUED", "RUNNING")),
        )
        .with_for_update()
    )
    if active is not None:
        if not reuse_active:
            raise HTTPException(status_code=409, detail="XML recovery is already running")
        queued_document_ids = set(
            await session.scalars(
                select(TaxXmlRecoveryItem.fiscal_document_id).where(
                    TaxXmlRecoveryItem.tenant_id == context.tenant_id,
                    TaxXmlRecoveryItem.job_id == active.id,
                )
            )
        )
        documents = list(
            await session.scalars(
                select(FiscalDocument)
                .where(
                    FiscalDocument.tenant_id == context.tenant_id,
                    FiscalDocument.tax_period_id == period_id,
                    FiscalDocument.direction == "RECIBIDO",
                    FiscalDocument.is_preliminary.is_(True),
                    FiscalDocument.access_key.is_not(None),
                )
                .order_by(FiscalDocument.issue_date, FiscalDocument.id)
            )
        )
        new_documents = [
            document
            for document in documents
            if document.id not in queued_document_ids
            and document.access_key
            and access_key_service.verify_access_key(document.access_key)
        ]
        session.add_all(
            [
                TaxXmlRecoveryItem(
                    tenant_id=context.tenant_id,
                    job_id=active.id,
                    fiscal_document_id=document.id,
                    status="PENDING",
                )
                for document in new_documents
            ]
        )
        active.total_count += len(new_documents)
        await session.flush()
        return active

    documents = list(
        await session.scalars(
            select(FiscalDocument)
            .where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.tax_period_id == period_id,
                FiscalDocument.direction == "RECIBIDO",
                FiscalDocument.is_preliminary.is_(True),
                FiscalDocument.access_key.is_not(None),
            )
            .order_by(FiscalDocument.issue_date, FiscalDocument.id)
        )
    )
    eligible = [
        document
        for document in documents
        if document.access_key and access_key_service.verify_access_key(document.access_key)
    ]
    job = TaxXmlRecoveryJob(
        tenant_id=context.tenant_id,
        tax_period_id=period_id,
        status="QUEUED" if eligible else "COMPLETED",
        total_count=len(eligible),
        requested_by_actor_id=context.actor_id,
        requested_by_actor_type=context.actor_type,
    )
    session.add(job)
    await session.flush()
    session.add_all(
        [
            TaxXmlRecoveryItem(
                tenant_id=context.tenant_id,
                job_id=job.id,
                fiscal_document_id=document.id,
                status="PENDING",
            )
            for document in eligible
        ]
    )
    await session.flush()
    return job


async def latest_job(
    session: AsyncSession,
    context: AuthContext,
    *,
    period_id: uuid.UUID,
) -> TaxXmlRecoveryJob | None:
    job: TaxXmlRecoveryJob | None = await session.scalar(
        select(TaxXmlRecoveryJob)
        .where(
            TaxXmlRecoveryJob.tenant_id == context.tenant_id,
            TaxXmlRecoveryJob.tax_period_id == period_id,
        )
        .order_by(TaxXmlRecoveryJob.created_at.desc(), TaxXmlRecoveryJob.id.desc())
        .limit(1)
    )
    return job


async def unresolved_items(
    session: AsyncSession,
    context: AuthContext,
    *,
    job_id: uuid.UUID,
) -> list[TaxXmlRecoveryItem]:
    """Ítems que requieren acción humana; no expone claves ni XML."""
    return list(
        await session.scalars(
            select(TaxXmlRecoveryItem)
            .where(
                TaxXmlRecoveryItem.tenant_id == context.tenant_id,
                TaxXmlRecoveryItem.job_id == job_id,
                TaxXmlRecoveryItem.status.in_(("UNAVAILABLE", "FAILED")),
            )
            .order_by(TaxXmlRecoveryItem.created_at, TaxXmlRecoveryItem.id)
        )
    )


__all__ = [
    "RECOVERY_REQUESTED_EVENT",
    "create_job",
    "latest_job",
    "unresolved_items",
]

"""Periodos tributarios por entidad, anio, mes y obligacion (ADR 0012)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import Tenant
from app.models.tax import FiscalDocument, FiscalDocumentTax, TaxEvidence, TaxPeriod
from app.services.tax import due_dates
from app.services.tax.completeness import missing_tax_detail_document_ids
from app.services.tax.external_purchases import external_payment_details, external_review_reasons
from app.services.tax.iva import compute_iva


async def _computed_due_date(
    session: AsyncSession,
    context: AuthContext,
    *,
    year: int,
    month: int,
    obligation_type: str,
) -> date | None:
    """Fecha limite segun el noveno digito del RUC, o ``None`` si no aplica.

    Queda ``None`` cuando la obligacion no tiene calendario confirmado o el RUC
    del tenant no es legible: ``services/tax/due_dates.py`` prefiere no dar
    fecha antes que dar una inventada.
    """
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None:
        return None
    computed = due_dates.due_date_for_period(
        obligation_type=obligation_type,
        year=year,
        month=month,
        ruc=tenant.ruc,
    )
    return computed.due_date if computed is not None else None


async def list_periods(
    session: AsyncSession,
    context: AuthContext,
    *,
    year: int | None = None,
    obligation_type: str | None = None,
) -> list[TaxPeriod]:
    query = select(TaxPeriod).where(TaxPeriod.tenant_id == context.tenant_id)
    if year is not None:
        query = query.where(TaxPeriod.year == year)
    if obligation_type is not None:
        query = query.where(TaxPeriod.obligation_type == obligation_type)
    result = await session.scalars(
        query.order_by(
            TaxPeriod.year.desc(),
            TaxPeriod.month.desc(),
            TaxPeriod.obligation_type,
        )
    )
    return list(result)


async def get_or_create_period(
    session: AsyncSession,
    context: AuthContext,
    *,
    year: int,
    month: int,
    obligation_type: str,
    due_date: date | None = None,
    notes: str | None = None,
) -> TaxPeriod:
    """Devuelve el periodo, creandolo si no existe.

    Un periodo nuevo arranca en ``PENDIENTE_DESCARGA``: sin evidencia cargada no
    hay nada que revisar ni declarar.

    Si no se pasa ``due_date``, se calcula desde el noveno digito del RUC. Una
    fecha explicita siempre gana: la persona que la escribe sabe de un caso que
    la regla general no cubre (regimen especial, prorroga) y el calculo no debe
    pisarla.
    """
    lookup = select(TaxPeriod).where(
        TaxPeriod.tenant_id == context.tenant_id,
        TaxPeriod.year == year,
        TaxPeriod.month == month,
        TaxPeriod.obligation_type == obligation_type,
    )
    existing: TaxPeriod | None = await session.scalar(lookup.with_for_update())
    if existing is not None:
        return existing

    if due_date is None:
        due_date = await _computed_due_date(
            session,
            context,
            year=year,
            month=month,
            obligation_type=obligation_type,
        )

    period = TaxPeriod(
        tenant_id=context.tenant_id,
        year=year,
        month=month,
        obligation_type=obligation_type,
        status="PENDIENTE_DESCARGA",
        due_date=due_date,
        notes=notes,
    )
    try:
        async with session.begin_nested():
            session.add(period)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(lookup.with_for_update())
        if existing is None:
            raise
        return existing
    return period


async def get_period(
    session: AsyncSession,
    context: AuthContext,
    *,
    period_id: uuid.UUID,
) -> TaxPeriod:
    period = await session.scalar(
        select(TaxPeriod).where(
            TaxPeriod.tenant_id == context.tenant_id,
            TaxPeriod.id == period_id,
        )
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Tax period not found")
    return period


async def refresh_period_statuses(
    session: AsyncSession,
    context: AuthContext,
    *,
    period_id: uuid.UUID | None = None,
) -> list[TaxPeriod]:
    """Actualiza estados derivados de la evidencia, sin reabrir declarados."""
    query = select(TaxPeriod).where(
        TaxPeriod.tenant_id == context.tenant_id,
        TaxPeriod.status != "DECLARADO",
    )
    if period_id is not None:
        query = query.where(TaxPeriod.id == period_id)
    periods = list(
        await session.scalars(query)
    )
    for period in periods:
        documents = list(
            await session.scalars(
                select(FiscalDocument).where(
                    FiscalDocument.tenant_id == context.tenant_id,
                    FiscalDocument.tax_period_id == period.id,
                )
            )
        )
        document_ids = [document.id for document in documents]
        tax_document_ids = (
            set(
                await session.scalars(
                    select(FiscalDocumentTax.fiscal_document_id).where(
                        FiscalDocumentTax.tenant_id == context.tenant_id,
                        FiscalDocumentTax.fiscal_document_id.in_(document_ids),
                    )
                )
            )
            if document_ids
            else set()
        )
        manual_review = False
        if period.obligation_type in {"IVA", "ATS"}:
            payments = await external_payment_details(
                session, tenant_id=context.tenant_id, year=period.year, month=period.month
            )
            manual_review = bool(external_review_reasons(payments, documents))
        if manual_review:
            period.status = "EVIDENCIA_INCOMPLETA"
        elif not documents:
            period.status = "PENDIENTE_DESCARGA"
        elif any(
                document.is_preliminary and document.cancelled_at is None
                for document in documents
            ) or (
            missing_tax_detail_document_ids(documents, tax_document_ids)
        ):
            period.status = "EVIDENCIA_INCOMPLETA"
        elif period.status != "LISTO_DECLARAR":
            period.status = "LISTO_REVISAR"
    await session.flush()
    return periods


async def set_manual_status(
    session: AsyncSession,
    context: AuthContext,
    *,
    period_id: uuid.UUID,
    target_status: str,
    confirmed: bool,
    external_filing_evidence_id: uuid.UUID | None = None,
) -> TaxPeriod:
    """Avanza el cierre fiscal únicamente tras una confirmación humana."""
    if not confirmed:
        raise HTTPException(status_code=422, detail="Human confirmation is required")
    period = await session.scalar(
        select(TaxPeriod).where(TaxPeriod.id == period_id, TaxPeriod.tenant_id == context.tenant_id)
        .with_for_update()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Tax period not found")
    if external_filing_evidence_id is not None:
        if period.obligation_type != "IVA" or target_status != "DECLARADO":
            raise HTTPException(status_code=422, detail="El acuse acredita la declaración de IVA.")
        evidence = await session.scalar(
            select(TaxEvidence.id).where(
                TaxEvidence.id == external_filing_evidence_id,
                TaxEvidence.tenant_id == context.tenant_id,
                TaxEvidence.tax_period_id == period.id,
                TaxEvidence.origin == "ACUSE_IVA_SRI",
                TaxEvidence.file_type == "PDF",
            )
        )
        if evidence is None:
            raise HTTPException(status_code=422, detail="Adjunta el acuse de IVA de este período.")
        if period.status == "DECLARADO":
            raise HTTPException(status_code=409, detail="Este período ya consta como declarado.")
        summary = await compute_iva(session, context, period=period)
        if not summary.requires_external_review:
            raise HTTPException(
                status_code=409, detail="Este período admite la revisión ordinaria del formulario."
            )
        period.status = "DECLARADO"
        await session.flush()
        return period
    await refresh_period_statuses(session, context, period_id=period.id)
    if target_status == "LISTO_DECLARAR":
        if period.status != "LISTO_REVISAR":
            raise HTTPException(
                status_code=409,
                detail="Period must have complete evidence before it is ready to declare",
            )
    elif target_status == "DECLARADO":
        if period.status != "LISTO_DECLARAR":
            raise HTTPException(
                status_code=409,
                detail="Period must be ready to declare before marking it declared",
            )
    else:
        raise HTTPException(status_code=422, detail="Unsupported manual tax status")
    period.status = target_status
    await session.flush()
    return period


__all__ = [
    "get_or_create_period",
    "get_period",
    "list_periods",
    "refresh_period_statuses",
    "set_manual_status",
]

"""Periodos tributarios por entidad, anio, mes y obligacion (ADR 0012)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import Tenant
from app.models.tax import FiscalDocument, FiscalDocumentTax, TaxPeriod
from app.services.tax import due_dates
from app.services.tax.completeness import missing_tax_detail_document_ids


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
    existing = await session.scalar(
        select(TaxPeriod).where(
            TaxPeriod.tenant_id == context.tenant_id,
            TaxPeriod.year == year,
            TaxPeriod.month == month,
            TaxPeriod.obligation_type == obligation_type,
        )
    )
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
    session.add(period)
    await session.flush()
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
        if not documents:
            period.status = "PENDIENTE_DESCARGA"
        elif any(document.is_preliminary for document in documents) or (
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
) -> TaxPeriod:
    """Avanza el cierre fiscal únicamente tras una confirmación humana."""
    if not confirmed:
        raise HTTPException(status_code=422, detail="Human confirmation is required")
    period = await get_period(session, context, period_id=period_id)
    await refresh_period_statuses(session, context)
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

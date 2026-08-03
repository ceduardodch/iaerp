"""Periodos tributarios por entidad, anio, mes y obligacion (ADR 0012)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument, TaxPeriod


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
) -> list[TaxPeriod]:
    """Actualiza estados derivados de la evidencia, sin reabrir declarados."""
    periods = list(
        await session.scalars(
            select(TaxPeriod).where(
                TaxPeriod.tenant_id == context.tenant_id,
                TaxPeriod.status != "DECLARADO",
            )
        )
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
        if not documents:
            period.status = "PENDIENTE_DESCARGA"
        elif any(document.is_preliminary for document in documents):
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

"""Periodos tributarios por entidad, anio, mes y obligacion (ADR 0012)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import TaxPeriod


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


__all__ = ["get_or_create_period", "get_period", "list_periods"]

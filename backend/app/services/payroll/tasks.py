"""Programador que abre el borrador del periodo del mes en curso.

Corre en bucle desde ``workers/dispatcher.py`` y, para cada tenant con al
menos un empleado de nomina, llama a ``generate_draft_period`` sobre el
(anio, mes) del dia actual en hora de Ecuador. Es seguro repetirlo: mientras
el periodo siga en ``DRAFT`` solo recalcula sus entradas (igual que una
llamada manual), y si ya fue aprobado ``generate_draft_period`` responde 409,
que aqui se ignora por tenant en vez de interrumpir el resto de la corrida.
Nunca aprueba nada -- eso sigue siendo una accion humana explicita.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.payroll import PayrollEmployee
from app.services.payroll.periods import generate_draft_period

FISCAL_TZ = ZoneInfo("America/Guayaquil")


def _scheduler_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        actor_id="payroll-scheduler",
        actor_type="SYSTEM",
        tenant_id=tenant_id,
        roles=frozenset({"scheduler"}),
        scopes=frozenset({"payroll:write"}),
        token_id="payroll-scheduler",
    )


async def generate_current_period_drafts_once(*, today: date | None = None) -> int:
    """Abre el borrador del mes en curso para cada tenant con empleados.

    Devuelve cuantos tenants tienen ahora un periodo en DRAFT para ese mes
    (ya sea creado o solo recalculado en esta corrida); los que ya estaban
    APPROVED no cuentan.
    """
    current = today or datetime.now(FISCAL_TZ).date()
    async with SessionFactory() as session:
        tenant_ids = list(
            (await session.scalars(select(PayrollEmployee.tenant_id).distinct())).all()
        )

    processed = 0
    for tenant_id in tenant_ids:
        context = _scheduler_context(tenant_id)
        async with SessionFactory() as session, session.begin():
            try:
                await generate_draft_period(
                    session, context, anio=current.year, mes=current.month
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
        processed += 1
    return processed


async def run_payroll_scheduler() -> None:
    while True:
        await generate_current_period_drafts_once()
        await asyncio.sleep(60)


__all__ = ["generate_current_period_drafts_once", "run_payroll_scheduler"]

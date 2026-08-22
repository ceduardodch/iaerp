"""Generacion del borrador de un periodo y su aprobacion.

Generar el borrador es idempotente: se puede llamar varias veces sobre el
mismo ``(tenant, anio, mes)`` mientras el periodo siga en ``DRAFT`` -- cada
llamada vuelve a calcular el rol de cada empleado vigente y reemplaza sus
entradas (borrar + reinsertar), asi que dos corridas seguidas producen el
mismo resultado sin duplicar filas. Aprobar es la unica transicion que cierra
el periodo: desde ahi regenerar el borrador ya no esta permitido, porque
cambiaria un rol que ya se dio por bueno.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.payroll import PayrollEmployee, PayrollEntry, PayrollPeriod
from app.services.payroll.calculations import calcular_rol


async def _get_or_create_period(
    session: AsyncSession,
    context: AuthContext,
    anio: int,
    mes: int,
) -> PayrollPeriod:
    period = await session.scalar(
        select(PayrollPeriod)
        .where(
            PayrollPeriod.tenant_id == context.tenant_id,
            PayrollPeriod.anio == anio,
            PayrollPeriod.mes == mes,
        )
        .with_for_update()
    )
    if period is not None:
        return period
    period = PayrollPeriod(tenant_id=context.tenant_id, anio=anio, mes=mes, status="DRAFT")
    session.add(period)
    await session.flush()
    return period


async def _employees_vigentes_en(
    session: AsyncSession,
    context: AuthContext,
    inicio_mes: date,
    fin_mes: date,
) -> list[PayrollEmployee]:
    """Empleados con derecho a rol en el mes, hayan sido dados de baja o no.

    Un empleado que sale a mitad de mes sigue cobrando ese mes proporcional;
    por eso el filtro es por fecha, no por la bandera ``active``.
    """
    return list(
        (
            await session.scalars(
                select(PayrollEmployee)
                .where(
                    PayrollEmployee.tenant_id == context.tenant_id,
                    PayrollEmployee.fecha_ingreso <= fin_mes,
                    or_(
                        PayrollEmployee.fecha_salida.is_(None),
                        PayrollEmployee.fecha_salida >= inicio_mes,
                    ),
                )
                .order_by(PayrollEmployee.full_name)
            )
        ).all()
    )


async def generate_draft_period(
    session: AsyncSession,
    context: AuthContext,
    *,
    anio: int,
    mes: int,
) -> tuple[PayrollPeriod, list[PayrollEntry]]:
    period = await _get_or_create_period(session, context, anio, mes)
    if period.status == "APPROVED":
        raise HTTPException(
            status_code=409,
            detail="El periodo ya fue aprobado; no se puede regenerar el borrador",
        )

    inicio_mes = date(anio, mes, 1)
    fin_mes = date(anio, mes, monthrange(anio, mes)[1])
    employees = await _employees_vigentes_en(session, context, inicio_mes, fin_mes)

    await session.execute(
        delete(PayrollEntry).where(
            PayrollEntry.tenant_id == context.tenant_id,
            PayrollEntry.period_id == period.id,
        )
    )

    entries: list[PayrollEntry] = []
    for employee in employees:
        rol = calcular_rol(
            {
                "sueldo_mensual": employee.sueldo_mensual,
                "fecha_ingreso": employee.fecha_ingreso,
                "fecha_salida": employee.fecha_salida,
                "decimo_tercero_mensualizado": employee.decimo_tercero_mensualizado,
                "decimo_cuarto_mensualizado": employee.decimo_cuarto_mensualizado,
                "fondos_reserva_mensualizados": employee.fondos_reserva_mensualizados,
            },
            anio=anio,
            mes=mes,
        )
        entry = PayrollEntry(
            tenant_id=context.tenant_id,
            period_id=period.id,
            employee_id=employee.id,
            dias_trabajados=rol.dias_trabajados,
            imponible=rol.imponible,
            decimo_tercero=rol.decimo_tercero,
            decimo_cuarto=rol.decimo_cuarto,
            fondos_reserva=rol.fondos_reserva,
            total_ingresos=rol.total_ingresos,
            aporte_iess=rol.aporte_iess,
            total_descuentos=rol.total_descuentos,
            liquido=rol.liquido,
            sbu_aplicado=rol.sbu_aplicado,
            tasa_iess_aplicada=rol.tasa_iess_aplicada,
            tasa_fondos_aplicada=rol.tasa_fondos_aplicada,
        )
        session.add(entry)
        entries.append(entry)

    await session.flush()
    return period, entries


async def approve_period(
    session: AsyncSession,
    context: AuthContext,
    period_id: uuid.UUID,
) -> PayrollPeriod:
    period = await session.scalar(
        select(PayrollPeriod)
        .where(
            PayrollPeriod.id == period_id,
            PayrollPeriod.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if period is None:
        raise HTTPException(status_code=404, detail="Payroll period not found")
    if period.status == "APPROVED":
        return period

    has_entries = await session.scalar(
        select(PayrollEntry.id)
        .where(
            PayrollEntry.tenant_id == context.tenant_id,
            PayrollEntry.period_id == period.id,
        )
        .limit(1)
    )
    if has_entries is None:
        raise HTTPException(
            status_code=422,
            detail="No se puede aprobar un periodo sin roles generados",
        )

    period.status = "APPROVED"
    await session.flush()
    return period


__all__ = ["approve_period", "generate_draft_period"]

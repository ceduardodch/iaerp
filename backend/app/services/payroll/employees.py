"""Alta, edicion y baja de empleados de nomina.

Un empleado dado de baja no se borra: ``active`` pasa a ``False`` y
``fecha_salida`` queda registrada para que ``calculations.py`` siga
prorrateando correctamente el mes en que dejo de trabajar. Por eso la baja no
reutiliza ``update_employee`` con un campo mas: es una transicion de estado
propia, no una edicion de datos.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.db.integrity import unique_constraint_name
from app.models.payroll import PayrollEmployee
from app.schemas.payroll import (
    PayrollEmployeeCreate,
    PayrollEmployeeTerminate,
    PayrollEmployeeUpdate,
)

_DUPLICATE_IDENTIFICATION_CONSTRAINT = "uq_payroll_employees_tenant_identification"


async def list_employees(
    session: AsyncSession,
    context: AuthContext,
) -> list[PayrollEmployee]:
    return list(
        (
            await session.scalars(
                select(PayrollEmployee)
                .where(
                    PayrollEmployee.tenant_id == context.tenant_id,
                    PayrollEmployee.active.is_(True),
                )
                .order_by(PayrollEmployee.full_name)
            )
        ).all()
    )


async def create_employee(
    session: AsyncSession,
    context: AuthContext,
    data: PayrollEmployeeCreate,
) -> PayrollEmployee:
    entity = PayrollEmployee(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError as exc:
        if unique_constraint_name(exc) == _DUPLICATE_IDENTIFICATION_CONSTRAINT:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ya existe un empleado con la identificación "
                    f"{data.identification_number}"
                ),
            ) from exc
        raise
    return entity


async def _get_active_employee(
    session: AsyncSession,
    context: AuthContext,
    employee_id: uuid.UUID,
) -> PayrollEmployee:
    entity = await session.scalar(
        select(PayrollEmployee)
        .where(
            PayrollEmployee.id == employee_id,
            PayrollEmployee.tenant_id == context.tenant_id,
            PayrollEmployee.active.is_(True),
        )
        .with_for_update()
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Payroll employee not found")
    return entity


async def update_employee(
    session: AsyncSession,
    context: AuthContext,
    employee_id: uuid.UUID,
    data: PayrollEmployeeUpdate,
) -> PayrollEmployee:
    entity = await _get_active_employee(session, context, employee_id)
    for field, value in data.model_dump(by_alias=False).items():
        setattr(entity, field, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        if unique_constraint_name(exc) == _DUPLICATE_IDENTIFICATION_CONSTRAINT:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ya existe un empleado con la identificación "
                    f"{data.identification_number}"
                ),
            ) from exc
        raise
    return entity


async def deactivate_employee(
    session: AsyncSession,
    context: AuthContext,
    employee_id: uuid.UUID,
    data: PayrollEmployeeTerminate,
) -> PayrollEmployee:
    entity = await _get_active_employee(session, context, employee_id)
    if data.fecha_salida < entity.fecha_ingreso:
        raise HTTPException(
            status_code=422,
            detail="La fecha de salida no puede ser anterior a la fecha de ingreso",
        )
    entity.fecha_salida = data.fecha_salida
    entity.active = False
    await session.flush()
    return entity


__all__ = [
    "create_employee",
    "deactivate_employee",
    "list_employees",
    "update_employee",
]

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.payroll import (
    PayrollEmployeeCreate,
    PayrollEmployeeRead,
    PayrollEmployeeTerminate,
    PayrollEmployeeUpdate,
    PayrollEntryRead,
    PayrollPeriodDraftCreate,
    PayrollPeriodRead,
)
from app.services.payroll import employees, periods
from app.services.unit_of_work import execute_idempotent

router = APIRouter(tags=["payroll"])

Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]


@router.get(
    "/payroll/employees",
    response_model=list[PayrollEmployeeRead],
    summary="Listar empleados de nómina activos",
)
async def get_payroll_employees(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:read"))],
) -> list[PayrollEmployeeRead]:
    entities = await employees.list_employees(session, context)
    return [PayrollEmployeeRead.model_validate(entity) for entity in entities]


@router.post(
    "/payroll/employees",
    response_model=PayrollEmployeeRead,
    status_code=201,
    summary="Dar de alta un empleado de nómina",
)
async def post_payroll_employee(
    data: PayrollEmployeeCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await employees.create_employee(session, context, data)
        read = PayrollEmployeeRead.model_validate(entity)
        return str(entity.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payroll.employees.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payroll_employee.created",
        entity_type="payroll_employee",
        callback=create,
    )


@router.put(
    "/payroll/employees/{employee_id}",
    response_model=PayrollEmployeeRead,
    summary="Editar un empleado de nómina",
)
async def put_payroll_employee(
    employee_id: uuid.UUID,
    data: PayrollEmployeeUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await employees.update_employee(session, context, employee_id, data)
        read = PayrollEmployeeRead.model_validate(entity)
        return str(entity.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payroll.employees.update",
        idempotency_key=idempotency_key,
        request_payload={"employeeId": str(employee_id), **data.model_dump(mode="json")},
        action="payroll_employee.updated",
        entity_type="payroll_employee",
        callback=update,
    )


@router.post(
    "/payroll/employees/{employee_id}/terminate",
    response_model=PayrollEmployeeRead,
    summary="Dar de baja a un empleado de nómina",
)
async def post_payroll_employee_terminate(
    employee_id: uuid.UUID,
    data: PayrollEmployeeTerminate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:write"))],
) -> dict[str, object]:
    async def terminate() -> tuple[str, dict[str, object]]:
        entity = await employees.deactivate_employee(session, context, employee_id, data)
        read = PayrollEmployeeRead.model_validate(entity)
        return str(entity.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payroll.employees.terminate",
        idempotency_key=idempotency_key,
        request_payload={"employeeId": str(employee_id), **data.model_dump(mode="json")},
        action="payroll_employee.terminated",
        entity_type="payroll_employee",
        callback=terminate,
    )


@router.get(
    "/payroll/periods",
    response_model=list[PayrollPeriodRead],
    summary="Listar periodos de nómina",
)
async def get_payroll_periods(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:read"))],
) -> list[PayrollPeriodRead]:
    entities = await periods.list_periods(session, context)
    return [PayrollPeriodRead.model_validate(entity) for entity in entities]


@router.get(
    "/payroll/periods/{period_id}/entries",
    response_model=list[PayrollEntryRead],
    summary="Listar los roles calculados de un periodo",
)
async def get_payroll_period_entries(
    period_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:read"))],
) -> list[PayrollEntryRead]:
    entities = await periods.list_entries(session, context, period_id)
    return [PayrollEntryRead.model_validate(entity) for entity in entities]


@router.post(
    "/payroll/periods/draft",
    response_model=PayrollPeriodRead,
    summary="Generar (o regenerar) el borrador de un periodo",
)
async def post_payroll_period_draft(
    data: PayrollPeriodDraftCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:write"))],
) -> dict[str, object]:
    async def generate() -> tuple[str, dict[str, object]]:
        period, _entries = await periods.generate_draft_period(
            session, context, anio=data.anio, mes=data.mes
        )
        read = PayrollPeriodRead.model_validate(period)
        return str(period.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payroll.periods.generate_draft",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payroll_period.draft_generated",
        entity_type="payroll_period",
        callback=generate,
    )


@router.post(
    "/payroll/periods/{period_id}/approve",
    response_model=PayrollPeriodRead,
    summary="Aprobar un periodo de nómina",
)
async def post_payroll_period_approve(
    period_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payroll:write"))],
) -> dict[str, object]:
    async def approve() -> tuple[str, dict[str, object]]:
        period = await periods.approve_period(session, context, period_id)
        read = PayrollPeriodRead.model_validate(period)
        return str(period.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payroll.periods.approve",
        idempotency_key=idempotency_key,
        request_payload={"periodId": str(period_id)},
        action="payroll_period.approved",
        entity_type="payroll_period",
        callback=approve,
    )

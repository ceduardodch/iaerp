"""Unitarias del programador que abre el borrador del mes en curso.

Sin HTTP y sin ``asyncio.TaskGroup``: solo prueba ``generate_current_period_drafts_once``,
la funcion que ``run_payroll_scheduler`` llama en bucle desde
``workers/dispatcher.py``.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.payroll import PayrollEntry, PayrollPeriod
from app.schemas.payroll import PayrollEmployeeCreate
from app.services.payroll.employees import create_employee
from app.services.payroll.periods import approve_period
from app.services.payroll.tasks import generate_current_period_drafts_once

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _context(*, tenant_id: uuid.UUID = TENANT_A) -> AuthContext:
    return AuthContext(
        actor_id="tester@iaerp.local",
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset({"payroll:write"}),
        token_id="test-token",
    )


def _employee_payload(**overrides: object) -> PayrollEmployeeCreate:
    fields: dict[str, object] = {
        "full_name": "Ana Torres",
        "identification_number": "1712345678",
        "sueldo_mensual": Decimal("1000.00"),
        "fecha_ingreso": date(2020, 1, 1),
    }
    fields.update(overrides)
    return PayrollEmployeeCreate(**fields)


async def test_scheduler_drafts_current_month_for_tenants_with_employees() -> None:
    async with SessionFactory() as session, session.begin():
        await create_employee(session, _context(tenant_id=TENANT_A), _employee_payload())
        await create_employee(session, _context(tenant_id=TENANT_B), _employee_payload())

    processed = await generate_current_period_drafts_once(today=date(2026, 6, 10))
    assert processed == 2

    async with SessionFactory() as session:
        periods = list(
            (
                await session.scalars(
                    select(PayrollPeriod).where(
                        PayrollPeriod.anio == 2026, PayrollPeriod.mes == 6
                    )
                )
            ).all()
        )
    assert {period.tenant_id for period in periods} == {TENANT_A, TENANT_B}
    for period in periods:
        assert period.status == "DRAFT"


async def test_scheduler_ignores_tenants_without_employees() -> None:
    processed = await generate_current_period_drafts_once(today=date(2026, 6, 10))
    assert processed == 0

    async with SessionFactory() as session:
        periods = list((await session.scalars(select(PayrollPeriod))).all())
    assert periods == []


async def test_scheduler_is_idempotent_and_does_not_duplicate_entries() -> None:
    async with SessionFactory() as session, session.begin():
        await create_employee(session, _context(), _employee_payload())

    await generate_current_period_drafts_once(today=date(2026, 6, 10))
    await generate_current_period_drafts_once(today=date(2026, 6, 10))

    async with SessionFactory() as session:
        periods = list((await session.scalars(select(PayrollPeriod))).all())
        assert len(periods) == 1
        entries = list(
            (
                await session.scalars(
                    select(PayrollEntry).where(PayrollEntry.period_id == periods[0].id)
                )
            ).all()
        )
    assert len(entries) == 1


async def test_scheduler_skips_approved_period_without_raising() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _employee_payload())

    await generate_current_period_drafts_once(today=date(2026, 6, 10))

    async with SessionFactory() as session:
        period = await session.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.tenant_id == TENANT_A,
                PayrollPeriod.anio == 2026,
                PayrollPeriod.mes == 6,
            )
        )
    assert period is not None
    async with SessionFactory() as session, session.begin():
        await approve_period(session, context, period.id)

    # Debe seguir corriendo sin romperse aunque el periodo ya este aprobado
    # y no pueda regenerarse.
    processed = await generate_current_period_drafts_once(today=date(2026, 6, 10))
    assert processed == 0

    async with SessionFactory() as session:
        stored = await session.get(PayrollPeriod, period.id)
    assert stored is not None
    assert stored.status == "APPROVED"

"""Unitarias de ``services/payroll/periods.py``: borrador y aprobacion.

Sin HTTP: los endpoints ``/payroll/*`` llegan en un pendiente posterior
(``docs/NOMINA_PENDIENTES.md``).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.payroll import PayrollEntry, PayrollPeriod
from app.schemas.payroll import PayrollEmployeeCreate, PayrollEmployeeTerminate
from app.services.payroll.employees import create_employee, deactivate_employee
from app.services.payroll.periods import approve_period, generate_draft_period

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


async def _entries_for(period_id: uuid.UUID) -> list[PayrollEntry]:
    async with SessionFactory() as session:
        return list(
            (
                await session.scalars(
                    select(PayrollEntry).where(PayrollEntry.period_id == period_id)
                )
            ).all()
        )


async def test_generate_draft_period_creates_period_and_entry() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        employee = await create_employee(session, context, _employee_payload())

    async with SessionFactory() as session, session.begin():
        period, entries = await generate_draft_period(session, context, anio=2026, mes=6)

    assert period.anio == 2026
    assert period.mes == 6
    assert period.status == "DRAFT"
    assert [entry.employee_id for entry in entries] == [employee.id]
    assert entries[0].liquido == Decimal("1112.30")


async def test_generate_draft_period_is_idempotent() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _employee_payload())

    async with SessionFactory() as session, session.begin():
        period_first, _ = await generate_draft_period(session, context, anio=2026, mes=6)

    # Calling it again for the same (tenant, anio, mes) must not raise and
    # must not duplicate the period nor the entry.
    async with SessionFactory() as session, session.begin():
        period_second, entries_second = await generate_draft_period(
            session, context, anio=2026, mes=6
        )

    assert period_second.id == period_first.id
    assert len(entries_second) == 1

    async with SessionFactory() as session:
        periods = list(
            (
                await session.scalars(
                    select(PayrollPeriod).where(
                        PayrollPeriod.tenant_id == TENANT_A,
                        PayrollPeriod.anio == 2026,
                        PayrollPeriod.mes == 6,
                    )
                )
            ).all()
        )
    assert len(periods) == 1
    assert len(await _entries_for(period_first.id)) == 1


async def test_generate_draft_period_recalculates_after_employee_update() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        employee = await create_employee(session, context, _employee_payload())

    async with SessionFactory() as session, session.begin():
        await generate_draft_period(session, context, anio=2026, mes=6)

    from app.schemas.payroll import PayrollEmployeeUpdate
    from app.services.payroll.employees import update_employee

    async with SessionFactory() as session, session.begin():
        await update_employee(
            session,
            context,
            employee.id,
            PayrollEmployeeUpdate(
                full_name="Ana Torres",
                identification_number="1712345678",
                sueldo_mensual=Decimal("2000.00"),
                fecha_ingreso=date(2020, 1, 1),
            ),
        )

    async with SessionFactory() as session, session.begin():
        _, entries = await generate_draft_period(session, context, anio=2026, mes=6)

    assert len(entries) == 1
    assert entries[0].imponible == Decimal("2000.00")


async def test_generate_draft_period_excludes_employee_hired_later() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(
            session, context, _employee_payload(fecha_ingreso=date(2026, 7, 1))
        )

    async with SessionFactory() as session, session.begin():
        _, entries = await generate_draft_period(session, context, anio=2026, mes=6)

    assert entries == []


async def test_generate_draft_period_includes_employee_terminated_in_period() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        employee = await create_employee(session, context, _employee_payload())

    async with SessionFactory() as session, session.begin():
        await deactivate_employee(
            session, context, employee.id, PayrollEmployeeTerminate(fecha_salida=date(2026, 6, 15))
        )

    # The employee is now inactive, but must still get a prorated role for
    # the month they left.
    async with SessionFactory() as session, session.begin():
        _, entries = await generate_draft_period(session, context, anio=2026, mes=6)
    assert len(entries) == 1
    assert entries[0].dias_trabajados == 15

    # The following month they must no longer appear.
    async with SessionFactory() as session, session.begin():
        _, entries_next = await generate_draft_period(session, context, anio=2026, mes=7)
    assert entries_next == []


async def test_generate_draft_period_scoped_to_tenant() -> None:
    async with SessionFactory() as session, session.begin():
        await create_employee(session, _context(tenant_id=TENANT_A), _employee_payload())

    async with SessionFactory() as session, session.begin():
        _, entries = await generate_draft_period(
            session, _context(tenant_id=TENANT_B), anio=2026, mes=6
        )
    assert entries == []


async def test_approve_period_transitions_status() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _employee_payload())
    async with SessionFactory() as session, session.begin():
        period, _ = await generate_draft_period(session, context, anio=2026, mes=6)

    async with SessionFactory() as session, session.begin():
        approved = await approve_period(session, context, period.id)
    assert approved.status == "APPROVED"

    async with SessionFactory() as session:
        stored = await session.get(PayrollPeriod, period.id)
        assert stored is not None
        assert stored.status == "APPROVED"


async def test_approve_period_missing_raises_404() -> None:
    context = _context()
    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await approve_period(session, context, uuid.uuid4())
    assert exc_info.value.status_code == 404


async def test_approve_period_without_entries_raises_422() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        period = PayrollPeriod(tenant_id=context.tenant_id, anio=2026, mes=6, status="DRAFT")
        session.add(period)
        await session.flush()
        period_id = period.id

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await approve_period(session, context, period_id)
    assert exc_info.value.status_code == 422


async def test_approve_period_twice_is_idempotent() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _employee_payload())
    async with SessionFactory() as session, session.begin():
        period, _ = await generate_draft_period(session, context, anio=2026, mes=6)
    async with SessionFactory() as session, session.begin():
        await approve_period(session, context, period.id)

    async with SessionFactory() as session, session.begin():
        approved_again = await approve_period(session, context, period.id)
    assert approved_again.status == "APPROVED"


async def test_generate_draft_period_rejects_regeneration_after_approval() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _employee_payload())
    async with SessionFactory() as session, session.begin():
        period, _ = await generate_draft_period(session, context, anio=2026, mes=6)
    async with SessionFactory() as session, session.begin():
        await approve_period(session, context, period.id)

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await generate_draft_period(session, context, anio=2026, mes=6)
    assert exc_info.value.status_code == 409

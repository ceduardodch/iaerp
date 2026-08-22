"""Unitarias de ``services/payroll/employees.py``: alta, edicion y baja.

Sin HTTP: los endpoints ``/payroll/*`` llegan en un pendiente posterior
(``docs/NOMINA_PENDIENTES.md``).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.payroll import PayrollEmployee
from app.schemas.payroll import (
    PayrollEmployeeCreate,
    PayrollEmployeeTerminate,
    PayrollEmployeeUpdate,
)
from app.services.payroll.employees import (
    create_employee,
    deactivate_employee,
    list_employees,
    update_employee,
)

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


def _create_payload(**overrides: object) -> PayrollEmployeeCreate:
    fields: dict[str, object] = {
        "full_name": "Ana Torres",
        "identification_number": "1712345678",
        "sueldo_mensual": Decimal("500.00"),
        "fecha_ingreso": date(2025, 1, 6),
    }
    fields.update(overrides)
    return PayrollEmployeeCreate(**fields)


async def test_create_employee_persists_with_defaults() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        entity = await create_employee(session, context, _create_payload())

    async with SessionFactory() as session:
        stored = await session.get(PayrollEmployee, entity.id)
        assert stored is not None
        assert stored.full_name == "Ana Torres"
        assert stored.active is True
        assert stored.decimo_tercero_mensualizado is True
        assert stored.fecha_salida is None


async def test_create_employee_rejects_duplicate_identification_within_tenant() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        await create_employee(session, context, _create_payload())

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await create_employee(
                session, context, _create_payload(full_name="Otro Empleado")
            )
    assert exc_info.value.status_code == 409


async def test_create_employee_allows_same_identification_across_tenants() -> None:
    async with SessionFactory() as session, session.begin():
        await create_employee(session, _context(tenant_id=TENANT_A), _create_payload())
    async with SessionFactory() as session, session.begin():
        await create_employee(session, _context(tenant_id=TENANT_B), _create_payload())
    # No exception: identification numbers only need to be unique per tenant.


async def test_list_employees_excludes_inactive() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        active = await create_employee(session, context, _create_payload())
        terminated = await create_employee(
            session, context, _create_payload(identification_number="0912345678")
        )

    async with SessionFactory() as session, session.begin():
        await deactivate_employee(
            session,
            context,
            terminated.id,
            PayrollEmployeeTerminate(fecha_salida=date(2025, 6, 30)),
        )

    async with SessionFactory() as session, session.begin():
        employees = await list_employees(session, context)
    assert [employee.id for employee in employees] == [active.id]


async def test_update_employee_edits_fields() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        entity = await create_employee(session, context, _create_payload())

    update = PayrollEmployeeUpdate(
        full_name="Ana Maria Torres",
        identification_number="1712345678",
        position="Contadora",
        sueldo_mensual=Decimal("650.00"),
        fecha_ingreso=date(2025, 1, 6),
        decimo_tercero_mensualizado=False,
    )
    async with SessionFactory() as session, session.begin():
        updated = await update_employee(session, context, entity.id, update)
    assert updated.full_name == "Ana Maria Torres"
    assert updated.position == "Contadora"
    assert updated.sueldo_mensual == Decimal("650.00")
    assert updated.decimo_tercero_mensualizado is False

    async with SessionFactory() as session:
        stored = await session.get(PayrollEmployee, entity.id)
        assert stored is not None
        assert stored.position == "Contadora"


async def test_update_employee_missing_raises_404() -> None:
    context = _context()
    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await update_employee(session, context, uuid.uuid4(), _default_update())
    assert exc_info.value.status_code == 404


def _default_update(**overrides: object) -> PayrollEmployeeUpdate:
    fields: dict[str, object] = {
        "full_name": "Ana Torres",
        "identification_number": "1712345678",
        "sueldo_mensual": Decimal("500.00"),
        "fecha_ingreso": date(2025, 1, 6),
    }
    fields.update(overrides)
    return PayrollEmployeeUpdate(**fields)


async def test_deactivate_employee_sets_fecha_salida_and_inactive() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        entity = await create_employee(session, context, _create_payload())

    async with SessionFactory() as session, session.begin():
        terminated = await deactivate_employee(
            session,
            context,
            entity.id,
            PayrollEmployeeTerminate(fecha_salida=date(2025, 8, 15)),
        )
    assert terminated.active is False
    assert terminated.fecha_salida == date(2025, 8, 15)

    async with SessionFactory() as session:
        stored = await session.get(PayrollEmployee, entity.id)
        assert stored is not None
        assert stored.active is False


async def test_deactivate_employee_rejects_fecha_salida_before_ingreso() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        entity = await create_employee(
            session, context, _create_payload(fecha_ingreso=date(2025, 6, 1))
        )

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await deactivate_employee(
                session,
                context,
                entity.id,
                PayrollEmployeeTerminate(fecha_salida=date(2025, 5, 1)),
            )
    assert exc_info.value.status_code == 422


async def test_deactivate_already_inactive_employee_raises_404() -> None:
    context = _context()
    async with SessionFactory() as session, session.begin():
        entity = await create_employee(session, context, _create_payload())

    async with SessionFactory() as session, session.begin():
        await deactivate_employee(
            session,
            context,
            entity.id,
            PayrollEmployeeTerminate(fecha_salida=date(2025, 8, 15)),
        )

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await deactivate_employee(
                session,
                context,
                entity.id,
                PayrollEmployeeTerminate(fecha_salida=date(2025, 9, 1)),
            )
    assert exc_info.value.status_code == 404

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionFactory
from app.models.payroll import PayrollEmployee, PayrollEntry, PayrollPeriod

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _employee(tenant_id: uuid.UUID, **overrides: object) -> PayrollEmployee:
    fields: dict[str, object] = {
        "tenant_id": tenant_id,
        "full_name": "Ana Torres",
        "identification_number": "1712345678",
        "sueldo_mensual": Decimal("500.00"),
        "fecha_ingreso": date(2025, 1, 6),
    }
    fields.update(overrides)
    return PayrollEmployee(**fields)


def _period(tenant_id: uuid.UUID, **overrides: object) -> PayrollPeriod:
    fields: dict[str, object] = {"tenant_id": tenant_id, "anio": 2026, "mes": 1}
    fields.update(overrides)
    return PayrollPeriod(**fields)


async def test_payroll_employee_allows_same_identification_across_tenants():
    async with SessionFactory() as session, session.begin():
        session.add_all(
            [
                _employee(TENANT_A),
                _employee(TENANT_B),
            ]
        )
    # No exception: identification numbers only need to be unique per tenant.


async def test_payroll_employee_rejects_duplicate_identification_within_tenant():
    async with SessionFactory() as session, session.begin():
        session.add(_employee(TENANT_A))

    async with SessionFactory() as session:
        session.add(_employee(TENANT_A, full_name="Otro Empleado"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_payroll_employee_rejects_fecha_salida_before_ingreso():
    async with SessionFactory() as session:
        session.add(
            _employee(
                TENANT_A,
                fecha_ingreso=date(2025, 6, 1),
                fecha_salida=date(2025, 5, 1),
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_payroll_period_rejects_duplicate_anio_mes_within_tenant():
    async with SessionFactory() as session, session.begin():
        session.add(_period(TENANT_A))

    async with SessionFactory() as session:
        session.add(_period(TENANT_A))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_payroll_period_allows_same_anio_mes_across_tenants():
    async with SessionFactory() as session, session.begin():
        session.add_all([_period(TENANT_A), _period(TENANT_B)])
    # No exception: the (tenant_id, anio, mes) uniqueness is per tenant.


async def test_payroll_period_rejects_invalid_mes():
    async with SessionFactory() as session:
        session.add(_period(TENANT_A, mes=13))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_payroll_entry_rejects_duplicate_employee_within_period():
    async with SessionFactory() as session, session.begin():
        employee = _employee(TENANT_A)
        period = _period(TENANT_A)
        session.add_all([employee, period])
        await session.flush()
        entry_fields: dict[str, object] = {
            "tenant_id": TENANT_A,
            "period_id": period.id,
            "employee_id": employee.id,
            "dias_trabajados": 30,
            "imponible": Decimal("500.00"),
            "decimo_tercero": Decimal("41.67"),
            "decimo_cuarto": Decimal("40.17"),
            "fondos_reserva": Decimal("0.00"),
            "total_ingresos": Decimal("581.84"),
            "aporte_iess": Decimal("47.25"),
            "total_descuentos": Decimal("47.25"),
            "liquido": Decimal("534.59"),
            "sbu_aplicado": Decimal("482.00"),
            "tasa_iess_aplicada": Decimal("0.0945"),
            "tasa_fondos_aplicada": Decimal("0.0833"),
        }
        session.add(PayrollEntry(**entry_fields))
        await session.flush()

        with pytest.raises(IntegrityError):
            session.add(PayrollEntry(**entry_fields))
            await session.flush()

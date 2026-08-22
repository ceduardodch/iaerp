"""Modelos del contexto Nomina.

``PayrollEmployee`` es el sujeto de calculo (sueldo, fecha de ingreso/salida y
las tres banderas de mensualizacion que ``services/payroll/calculations.py``
ya consume). ``PayrollPeriod`` es el mes que se procesa, unico por
``(tenant_id, anio, mes)``. ``PayrollEntry`` es el resultado, un ``RolCalculado``
persistido por empleado y periodo -- sus columnas son deliberadamente las
mismas que ``RolCalculado`` para que el servicio que lo genere (siguiente
pendiente) sea un mapeo directo sin traduccion de campos.

Esta migracion solo declara el esquema: alta/edicion/baja de empleados y la
generacion/aprobacion de periodos llegan en pendientes posteriores
(``docs/NOMINA_PENDIENTES.md``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin

PAYROLL_PERIOD_STATUSES = frozenset({"DRAFT", "APPROVED"})


class PayrollEmployee(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Empleado sujeto a rol de pagos.

    No reutiliza ``Party``: un empleado no es necesariamente un cliente o
    proveedor, y sus campos (sueldo, fecha de ingreso, banderas de
    mensualizacion) no tienen equivalente ahi.
    """

    __tablename__ = "payroll_employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payroll_employees_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "identification_number",
            name="uq_payroll_employees_tenant_identification",
        ),
        CheckConstraint(
            "sueldo_mensual >= 0", name="ck_payroll_employees_sueldo_mensual_non_negative"
        ),
        CheckConstraint(
            "fecha_salida IS NULL OR fecha_salida >= fecha_ingreso",
            name="ck_payroll_employees_fecha_salida_after_ingreso",
        ),
    )

    full_name: Mapped[str] = mapped_column(String(200))
    identification_number: Mapped[str] = mapped_column(String(20))
    position: Mapped[str | None] = mapped_column(String(120))
    sueldo_mensual: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    fecha_salida: Mapped[date | None] = mapped_column(Date)
    decimo_tercero_mensualizado: Mapped[bool] = mapped_column(Boolean, default=True)
    decimo_cuarto_mensualizado: Mapped[bool] = mapped_column(Boolean, default=True)
    fondos_reserva_mensualizados: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PayrollPeriod(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Mes de nomina a procesar. Unico por tenant, anio y mes."""

    __tablename__ = "payroll_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_payroll_periods_tenant_id"),
        UniqueConstraint(
            "tenant_id", "anio", "mes", name="uq_payroll_periods_tenant_anio_mes"
        ),
        CheckConstraint("mes >= 1 AND mes <= 12", name="ck_payroll_periods_mes_valid"),
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED')", name="ck_payroll_periods_status_valid"
        ),
    )

    anio: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")


class PayrollEntry(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Rol calculado de un empleado en un periodo (mapeo de ``RolCalculado``).

    Unico por ``(tenant_id, period_id, employee_id)``: un empleado tiene a lo
    sumo un rol por periodo.
    """

    __tablename__ = "payroll_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["payroll_periods.tenant_id", "payroll_periods.id"],
            name="fk_payroll_entries_tenant_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["payroll_employees.tenant_id", "payroll_employees.id"],
            name="fk_payroll_entries_tenant_employee",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_payroll_entries_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "period_id",
            "employee_id",
            name="uq_payroll_entries_tenant_period_employee",
        ),
        CheckConstraint(
            "dias_trabajados >= 0 AND dias_trabajados <= 30",
            name="ck_payroll_entries_dias_trabajados_valid",
        ),
        CheckConstraint("imponible >= 0", name="ck_payroll_entries_imponible_non_negative"),
        CheckConstraint(
            "total_ingresos >= 0", name="ck_payroll_entries_total_ingresos_non_negative"
        ),
        CheckConstraint(
            "total_descuentos >= 0", name="ck_payroll_entries_total_descuentos_non_negative"
        ),
        CheckConstraint("liquido >= 0", name="ck_payroll_entries_liquido_non_negative"),
    )

    period_id: Mapped[uuid.UUID]
    employee_id: Mapped[uuid.UUID]
    dias_trabajados: Mapped[int] = mapped_column(Integer)
    imponible: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    decimo_tercero: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    decimo_cuarto: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fondos_reserva: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_ingresos: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    aporte_iess: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_descuentos: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    liquido: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    sbu_aplicado: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tasa_iess_aplicada: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    tasa_fondos_aplicada: Mapped[Decimal] = mapped_column(Numeric(9, 6))


__all__ = [
    "PAYROLL_PERIOD_STATUSES",
    "PayrollEmployee",
    "PayrollEntry",
    "PayrollPeriod",
]

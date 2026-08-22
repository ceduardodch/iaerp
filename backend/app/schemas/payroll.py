import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from app.schemas.base import APIModel


class PayrollEmployeeFields(APIModel):
    full_name: str = Field(min_length=1, max_length=200)
    identification_number: str = Field(min_length=1, max_length=20)
    position: str | None = Field(default=None, max_length=120)
    sueldo_mensual: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    fecha_ingreso: date
    decimo_tercero_mensualizado: bool = True
    decimo_cuarto_mensualizado: bool = True
    fondos_reserva_mensualizados: bool = True


class PayrollEmployeeCreate(PayrollEmployeeFields):
    pass


class PayrollEmployeeUpdate(PayrollEmployeeFields):
    pass


class PayrollEmployeeRead(PayrollEmployeeFields):
    id: uuid.UUID
    fecha_salida: date | None
    active: bool


class PayrollEmployeeTerminate(APIModel):
    """Baja del empleado: fecha en que deja de prestar servicios."""

    fecha_salida: date


class PayrollPeriodDraftCreate(APIModel):
    """Mes a procesar: genera o regenera el borrador de rol de pagos."""

    anio: int = Field(ge=2000, le=2100)
    mes: int = Field(ge=1, le=12)


class PayrollPeriodRead(APIModel):
    id: uuid.UUID
    anio: int
    mes: int
    status: str


class PayrollEntryRead(APIModel):
    id: uuid.UUID
    period_id: uuid.UUID
    employee_id: uuid.UUID
    dias_trabajados: int
    imponible: Decimal
    decimo_tercero: Decimal
    decimo_cuarto: Decimal
    fondos_reserva: Decimal
    total_ingresos: Decimal
    aporte_iess: Decimal
    total_descuentos: Decimal
    liquido: Decimal
    sbu_aplicado: Decimal
    tasa_iess_aplicada: Decimal
    tasa_fondos_aplicada: Decimal


__all__ = [
    "PayrollEmployeeCreate",
    "PayrollEmployeeFields",
    "PayrollEmployeeRead",
    "PayrollEmployeeTerminate",
    "PayrollEmployeeUpdate",
    "PayrollEntryRead",
    "PayrollPeriodDraftCreate",
    "PayrollPeriodRead",
]

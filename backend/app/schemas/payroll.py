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


__all__ = [
    "PayrollEmployeeCreate",
    "PayrollEmployeeFields",
    "PayrollEmployeeRead",
    "PayrollEmployeeTerminate",
    "PayrollEmployeeUpdate",
]

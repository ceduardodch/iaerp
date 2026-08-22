"""Calculo del rol de pagos mensual.

Funcion pura sobre ``Decimal``: sin sesion ni IO, para poder probar las reglas
legales directamente. Las cifras salen de ``parameters.py``.

Lo que la ley exige y aqui se hace explicito:

- El aporte al IESS se calcula SOLO sobre la remuneracion imponible. Los
  decimos y los fondos de reserva no forman parte de esa base.
- Los fondos de reserva no existen en los primeros 12 meses de servicio.
- Un decimo que el trabajador eligio acumular no se reparte en el mes: se paga
  en su fecha (24-dic el tercero; 15-ago o 15-mar el cuarto).
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.payroll.parameters import (
    APORTE_PERSONAL_IESS,
    MESES_PARA_FONDOS_RESERVA,
    TASA_FONDOS_RESERVA,
    sbu_de,
)

# La nomina ecuatoriana usa mes comercial de 30 dias para prorratear, aunque el
# mes calendario tenga 28 o 31.
DIAS_MES_COMERCIAL = 30


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RolCalculado:
    """Desglose de un rol. Los montos ya vienen redondeados a centavos."""

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


def _meses_de_servicio(fecha_ingreso: date, corte: date) -> int:
    """Meses cumplidos entre el ingreso y el corte."""
    meses = (corte.year - fecha_ingreso.year) * 12 + (corte.month - fecha_ingreso.month)
    if corte.day < fecha_ingreso.day:
        meses -= 1
    return max(meses, 0)


def _dias_trabajados(fecha_ingreso: date, fecha_salida: date | None, anio: int, mes: int) -> int:
    """Dias del mes que corresponden al empleado, sobre base 30.

    Quien entra o sale a mitad de mes cobra proporcional; pagarle el mes
    completo o no pagarle nada son los dos errores posibles.
    """
    ultimo_dia_calendario = monthrange(anio, mes)[1]
    inicio_mes = date(anio, mes, 1)
    fin_mes = date(anio, mes, ultimo_dia_calendario)

    if fecha_ingreso > fin_mes:
        return 0
    if fecha_salida is not None and fecha_salida < inicio_mes:
        return 0

    desde = max(fecha_ingreso, inicio_mes)
    hasta = min(fecha_salida, fin_mes) if fecha_salida is not None else fin_mes

    # El dia de ingreso cuenta, por eso el +1. Se topa en 30 para que un mes de
    # 31 dias no pague un dia de mas.
    dias = min((hasta - desde).days + 1, DIAS_MES_COMERCIAL)
    return max(dias, 0)


def calcular_rol(empleado: dict[str, Any], *, anio: int, mes: int) -> RolCalculado:
    """Rol de un empleado para un periodo.

    ``empleado`` trae ``sueldo_mensual``, ``fecha_ingreso``, ``fecha_salida`` y
    las tres banderas de mensualizacion.
    """
    sbu = sbu_de(anio)
    sueldo: Decimal = empleado["sueldo_mensual"]
    fecha_ingreso: date = empleado["fecha_ingreso"]
    fecha_salida: date | None = empleado.get("fecha_salida")

    dias = _dias_trabajados(fecha_ingreso, fecha_salida, anio, mes)
    imponible = _centavos(sueldo * Decimal(dias) / Decimal(DIAS_MES_COMERCIAL))

    # El aporte se calcula ANTES de sumar decimos y fondos: esos no son base
    # de aportacion.
    aporte_iess = _centavos(imponible * APORTE_PERSONAL_IESS)

    decimo_tercero = (
        _centavos(imponible / Decimal(12))
        if empleado["decimo_tercero_mensualizado"]
        else Decimal("0.00")
    )
    # El decimo cuarto es el SBU, no el sueldo: es igual para todos.
    decimo_cuarto = (
        _centavos(sbu / Decimal(12))
        if empleado["decimo_cuarto_mensualizado"]
        else Decimal("0.00")
    )

    fin_periodo = date(anio, mes, monthrange(anio, mes)[1])
    tiene_derecho_a_fondos = (
        _meses_de_servicio(fecha_ingreso, fin_periodo) >= MESES_PARA_FONDOS_RESERVA
    )
    fondos_reserva = (
        _centavos(imponible * TASA_FONDOS_RESERVA)
        if tiene_derecho_a_fondos and empleado["fondos_reserva_mensualizados"]
        else Decimal("0.00")
    )

    total_ingresos = imponible + decimo_tercero + decimo_cuarto + fondos_reserva
    total_descuentos = aporte_iess

    return RolCalculado(
        dias_trabajados=dias,
        imponible=imponible,
        decimo_tercero=decimo_tercero,
        decimo_cuarto=decimo_cuarto,
        fondos_reserva=fondos_reserva,
        total_ingresos=total_ingresos,
        aporte_iess=aporte_iess,
        total_descuentos=total_descuentos,
        liquido=total_ingresos - total_descuentos,
        sbu_aplicado=sbu,
        tasa_iess_aplicada=APORTE_PERSONAL_IESS,
        tasa_fondos_aplicada=TASA_FONDOS_RESERVA,
    )


__all__ = ["DIAS_MES_COMERCIAL", "RolCalculado", "calcular_rol"]

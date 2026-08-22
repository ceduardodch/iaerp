"""Parametros legales de nomina, por anio.

El SBU lo fija el Ministerio del Trabajo cada diciembre para el anio siguiente,
asi que vive aqui indexado por anio y no como un numero suelto en el calculo.
Un rol de un periodo viejo tiene que seguir usando el SBU de SU anio.

Cuando salga el acuerdo ministerial de diciembre hay que agregar la fila del
anio nuevo. ``test_payroll_legal.py`` falla si el anio en curso no esta, para
que el olvido se vea en CI y no en el rol de enero.
"""

from __future__ import annotations

from decimal import Decimal

# Salario Basico Unificado por anio.
#   2026: Acuerdo Ministerial MDT-2025-195, Registro Oficial Sup. 187 del
#         18-dic-2025, vigente desde el 1-ene-2026.
SBU_POR_ANIO: dict[int, Decimal] = {
    2025: Decimal("470.00"),
    2026: Decimal("482.00"),
}

# Aporte personal al IESS en el sector privado. El patronal (11,15%) no se
# descuenta al trabajador y por eso no entra en el rol.
APORTE_PERSONAL_IESS = Decimal("0.0945")

# Fondos de reserva: un mes de sueldo por cada anio trabajado, mensualizado
# (12 / 144 = 8,33%). Solo se genera desde el mes 13 de servicio.
TASA_FONDOS_RESERVA = Decimal("0.0833")

# Meses de servicio cumplidos que exige el Codigo del Trabajo para que el
# trabajador tenga derecho a fondos de reserva.
MESES_PARA_FONDOS_RESERVA = 12


class SbuNoRegistrado(LookupError):
    """El anio pedido no tiene SBU cargado."""


def sbu_de(anio: int) -> Decimal:
    """SBU vigente en ``anio``.

    Falla en vez de asumir el ultimo conocido: un rol calculado con el SBU
    equivocado paga mal el decimo cuarto, y eso tiene multa.
    """
    try:
        return SBU_POR_ANIO[anio]
    except KeyError as exc:
        raise SbuNoRegistrado(
            f"No hay SBU registrado para {anio}. Agregalo en "
            "app/services/payroll/parameters.py cuando salga el acuerdo ministerial."
        ) from exc


__all__ = [
    "APORTE_PERSONAL_IESS",
    "MESES_PARA_FONDOS_RESERVA",
    "SBU_POR_ANIO",
    "TASA_FONDOS_RESERVA",
    "SbuNoRegistrado",
    "sbu_de",
]

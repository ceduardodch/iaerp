"""Formato unico de importes del modulo tributario (ADR 0012).

Todo valor que el usuario copia al formulario del SRI, y todo importe que va en
un anexo XML, se escribe igual: **punto decimal, dos decimales y sin separador de
miles** (``1234.56``). Un solo helper evita que cada pantalla o generador invente
su propio formato.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def quantize_amount(value: Decimal | int | float | str) -> Decimal:
    """Redondea a dos decimales con ROUND_HALF_UP (criterio fiscal)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def format_amount(value: Decimal | int | float | str) -> str:
    """``1234.56``: punto decimal, dos decimales, sin separador de miles."""
    return f"{quantize_amount(value):f}"


__all__ = ["TWO_PLACES", "format_amount", "quantize_amount"]

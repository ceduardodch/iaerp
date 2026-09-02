"""Fecha limite de declaracion segun el noveno digito del RUC.

Prerequisito P0.1 de ``docs/NOTIFICATIONS_MODULE_PLAN.md``: hasta ahora
``TaxPeriod.due_date`` solo se llenaba si una persona la escribia a mano, asi
que un aviso del tipo "declara hasta tal fecha" no tenia de donde sacar la
fecha. Este modulo la calcula.

Reglas que aplica (Art. 158 del Reglamento para la aplicacion de la LRTI):

- El dia maximo de presentacion depende del **noveno digito del RUC**.
- El IVA de un mes se declara en el **mes siguiente**.
- Si el vencimiento cae en dia de descanso obligatorio o feriado, se traslada
  al **siguiente dia habil**.

Lo que este modulo NO hace, en linea con el ADR 0012 (no inventar valores):

- **No adivina calendarios que no estan confirmados.** Solo ``IVA`` mensual
  esta soportado; ``ATS``, ``RENTA``, ``RDEP`` y ``ADI`` devuelven ``None``
  hasta que el usuario confirme su calendario. Es preferible no mostrar fecha
  a mostrar una equivocada en un aviso que la gente va a obedecer.
- **No inventa feriados.** El corrimiento por fin de semana es seguro (sabado y
  domingo son descanso obligatorio siempre), pero los feriados ecuatorianos
  cambian de observancia por decreto, asi que se reciben desde afuera. Cuando
  no se entrega calendario, el resultado lo declara en ``holidays_checked`` y
  quien muestre la fecha debe advertir que falta verificar feriados.
- **No contempla regimenes semestrales.** ``TenantTaxProfile.tax_regime`` se
  guarda pero todavia no se usa en ninguna logica; un tenant con declaracion
  semestral necesita una regla propia que aun no existe.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

# Dia maximo de presentacion segun el noveno digito del RUC. Ningun valor pasa
# de 28, asi que la fecha base siempre existe incluso en febrero.
DEADLINE_DAY_BY_NINTH_DIGIT: dict[int, int] = {
    1: 10,
    2: 12,
    3: 14,
    4: 16,
    5: 18,
    6: 20,
    7: 22,
    8: 24,
    9: 26,
    0: 28,
}

# Obligaciones cuyo calendario esta confirmado. El resto devuelve None a
# proposito (ver docstring del modulo).
SUPPORTED_OBLIGATIONS = frozenset({"IVA"})

# Longitud del RUC ecuatoriano, igual que ``Tenant.ruc`` (String(13)).
RUC_LENGTH = 13

_SATURDAY = 5
# Tope defensivo del corrimiento: con un calendario de feriados corrupto el
# bucle no debe quedarse girando dentro del scheduler.
_MAX_SHIFT_DAYS = 15


@dataclass(frozen=True)
class TaxDueDate:
    """Fecha limite calculada y el rastro de como se llego a ella.

    ``base_date`` es la fecha que sale de la tabla del noveno digito, antes de
    correrla; ``due_date`` es la definitiva. ``holidays_checked`` en ``False``
    significa que no se recibio calendario de feriados: la fecha ya esquiva
    fines de semana, pero podria faltarle un corrimiento por feriado.
    """

    due_date: date
    base_date: date
    shifted: bool
    holidays_checked: bool


def ninth_digit(ruc: str) -> int | None:
    """Noveno digito del RUC, o ``None`` si el RUC no es utilizable.

    Un RUC mal cargado no puede tumbar al scheduler ni, peor, producir una
    fecha inventada: sin noveno digito no hay fecha y el aviso debe pedir que
    se corrija el dato.
    """
    digits = ruc.strip()
    if len(digits) != RUC_LENGTH or not digits.isdigit():
        return None
    return int(digits[8])


def next_business_day(day: date, *, holidays: Collection[date] | None = None) -> date:
    """Primer dia habil desde ``day`` inclusive.

    Salta sabados y domingos siempre; salta ademas las fechas de ``holidays``
    cuando se entrega ese calendario.
    """
    known_holidays = frozenset(holidays or ())
    candidate = day
    for _ in range(_MAX_SHIFT_DAYS):
        if candidate.weekday() < _SATURDAY and candidate not in known_holidays:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def declaration_month(*, year: int, month: int) -> tuple[int, int]:
    """Anio y mes en que se declara un periodo mensual: el mes siguiente."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def due_date_for_period(
    *,
    obligation_type: str,
    year: int,
    month: int,
    ruc: str,
    holidays: Collection[date] | None = None,
) -> TaxDueDate | None:
    """Fecha limite del periodo, o ``None`` si no se puede afirmar cual es.

    Devuelve ``None`` cuando la obligacion no tiene calendario confirmado o
    cuando el RUC no permite leer el noveno digito. Quien llame decide que
    hacer con esa ausencia; lo que no debe hacer es rellenarla con una
    estimacion.
    """
    if obligation_type not in SUPPORTED_OBLIGATIONS:
        return None
    digit = ninth_digit(ruc)
    if digit is None:
        return None
    declaration_year, declaration_month_number = declaration_month(year=year, month=month)
    base_date = date(
        declaration_year,
        declaration_month_number,
        DEADLINE_DAY_BY_NINTH_DIGIT[digit],
    )
    due_date = next_business_day(base_date, holidays=holidays)
    return TaxDueDate(
        due_date=due_date,
        base_date=base_date,
        shifted=due_date != base_date,
        holidays_checked=holidays is not None,
    )


__all__ = [
    "DEADLINE_DAY_BY_NINTH_DIGIT",
    "RUC_LENGTH",
    "SUPPORTED_OBLIGATIONS",
    "TaxDueDate",
    "declaration_month",
    "due_date_for_period",
    "next_business_day",
    "ninth_digit",
]

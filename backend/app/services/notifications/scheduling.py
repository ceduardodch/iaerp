"""Calculo puro de cuando corresponde un aviso. Sin base de datos.

Se aisla aqui para que las reglas de calendario se puedan probar sin montar un
tenant, y para que cada tipo de aviso nuevo reutilice la misma aritmetica en
vez de inventar la suya.

Todo se piensa en hora de Ecuador y se persiste en UTC, igual que
``workers/collections.py``: la fecha limite del SRI es un dia local, no un
instante universal, y a las 08:00 de Guayaquil le corresponden dos fechas UTC
distintas segun la epoca del anio si uno se descuida.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta

from app.core.timezones import FISCAL_TIMEZONE


def parse_offsets(raw: str | None) -> list[int]:
    """``"-7,-3,-1"`` -> ``[-7, -3, -1]``. Tolera vacios y espacios."""
    if not raw:
        return []
    offsets: list[int] = []
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        offsets.append(int(value))
    return offsets


def parse_days_of_month(raw: str | None) -> list[int]:
    """``"1,10"`` -> ``[1, 10]``, descartando lo que no sea un dia valido."""
    days: list[int] = []
    for value in parse_offsets(raw):
        if 1 <= value <= 31:
            days.append(value)
    return days


def clamp_day_of_month(*, year: int, month: int, day: int) -> date:
    """Dia del mes, recortado al ultimo dia real.

    Un aviso configurado para el 31 tiene que ocurrir igual en febrero. La
    alternativa -- saltarse el mes -- es peor: el usuario configuro "fin de
    mes" y esperaria un aviso.
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def local_send_datetime(day: date, *, send_hour: int) -> datetime:
    """Instante UTC que corresponde a ``day`` a las ``send_hour`` en Ecuador."""
    local = datetime.combine(day, time(hour=send_hour), tzinfo=FISCAL_TIMEZONE)
    return local.astimezone(UTC)


def offset_occurrences(
    *,
    due_date: date,
    offsets: list[int],
    today: date,
) -> list[int]:
    """Offsets cuya fecha cae hoy.

    Devuelve los offsets y no las fechas porque el offset es lo que identifica
    a la ocurrencia dentro de su periodo: es la parte estable de la clave de
    deduplicacion aunque la fecha limite se corrija despues.
    """
    return [offset for offset in offsets if due_date + timedelta(days=offset) == today]


def day_of_month_occurs(*, days: list[int], today: date) -> bool:
    return any(
        clamp_day_of_month(year=today.year, month=today.month, day=day) == today for day in days
    )


def last_business_day(*, year: int, month: int, holidays: frozenset[date] | None = None) -> date:
    """Ultimo dia habil del mes.

    Retrocede sobre sabados y domingos siempre, y sobre los feriados que se
    entreguen. Sin calendario de feriados el resultado puede caer en uno; quien
    lo muestre debe advertirlo, igual que hace ``services/tax/due_dates.py``.
    """
    known_holidays = holidays or frozenset()
    candidate = date(year, month, calendar.monthrange(year, month)[1])
    while candidate.weekday() >= 5 or candidate in known_holidays:
        candidate -= timedelta(days=1)
    return candidate


def describe_days_remaining(days: int) -> str:
    """Texto humano de la distancia al vencimiento, en espanol."""
    if days > 1:
        return f"faltan {days} dias"
    if days == 1:
        return "falta 1 dia"
    if days == 0:
        return "vence hoy"
    if days == -1:
        return "venció ayer"
    return f"venció hace {abs(days)} dias"


__all__ = [
    "clamp_day_of_month",
    "day_of_month_occurs",
    "describe_days_remaining",
    "last_business_day",
    "local_send_datetime",
    "offset_occurrences",
    "parse_days_of_month",
    "parse_offsets",
]

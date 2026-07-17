"""Zona horaria fiscal compartida entre Billing y Receivables.

``docs/03-domain-model.md`` exige que las fechas fiscales usen
``America/Guayaquil``; ``docs/sprints/sprint-03.md`` (decision 4) pide extraer
el ``ZoneInfo`` que ``services/billing.py`` ya tenia hardcodeado para que
``services/receivables.py`` (aging) reutilice exactamente el mismo objeto en
vez de duplicarlo.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

FISCAL_TIMEZONE = ZoneInfo("America/Guayaquil")


def today_in_fiscal_timezone() -> date:
    """Fecha de hoy en ``America/Guayaquil``, derivada de la hora UTC real."""

    return datetime.now(UTC).astimezone(FISCAL_TIMEZONE).date()


__all__ = ["FISCAL_TIMEZONE", "today_in_fiscal_timezone"]

"""backfill tax period due dates from the RUC ninth digit

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-02 16:00:00.000000

Los periodos creados antes de ``services/tax/due_dates.py`` quedaron con
``due_date`` en NULL porque nadie la escribio a mano. Esta migracion la calcula
para los periodos de IVA usando el noveno digito del RUC del tenant.

Es idempotente y conservadora:

- Solo toca filas con ``due_date IS NULL``; una fecha escrita a mano (o una
  prorroga) nunca se pisa.
- Solo toca ``obligation_type = 'IVA'``: es la unica obligacion con calendario
  confirmado (ver el modulo de servicio).
- Salta los tenants cuyo RUC no tiene 13 digitos: sin noveno digito legible no
  hay fecha, y una inventada seria peor que la ausencia.
- El downgrade **conserva los datos**. No se puede distinguir despues del hecho
  entre una fecha que puso esta migracion y una que escribio una persona, asi
  que borrarlas destruiria trabajo humano.

La tabla del noveno digito se repite aqui a proposito en vez de importarla del
servicio: una migracion congela el comportamiento del dia que se aplico y no
debe cambiar de resultado si el servicio evoluciona.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "c1d2e3f4a5b6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEADLINE_DAY_BY_NINTH_DIGIT = {
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

RUC_LENGTH = 13
_SATURDAY = 5
_MAX_SHIFT_DAYS = 15


def _next_business_day(day: date) -> date:
    """Corre sabados y domingos. Sin calendario de feriados disponible aqui."""
    candidate = day
    for _ in range(_MAX_SHIFT_DAYS):
        if candidate.weekday() < _SATURDAY:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _due_date(*, year: int, month: int, ruc: str) -> date | None:
    digits = (ruc or "").strip()
    if len(digits) != RUC_LENGTH or not digits.isdigit():
        return None
    declaration_year, declaration_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return _next_business_day(
        date(declaration_year, declaration_month, DEADLINE_DAY_BY_NINTH_DIGIT[int(digits[8])])
    )


def upgrade() -> None:
    connection = op.get_bind()
    pending = connection.execute(
        sa.text(
            """
            SELECT p.id, p.year, p.month, t.ruc
            FROM tax_periods AS p
            JOIN tenants AS t ON t.id = p.tenant_id
            WHERE p.due_date IS NULL
              AND p.obligation_type = 'IVA'
            """
        )
    ).fetchall()

    for period_id, year, month, ruc in pending:
        computed = _due_date(year=year, month=month, ruc=ruc)
        if computed is None:
            continue
        connection.execute(
            sa.text("UPDATE tax_periods SET due_date = :due_date WHERE id = :id"),
            {"due_date": computed, "id": period_id},
        )


def downgrade() -> None:
    """No-op deliberado: ver la nota del encabezado sobre conservar datos."""

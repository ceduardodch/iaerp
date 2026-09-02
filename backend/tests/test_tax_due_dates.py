"""Fecha limite de declaracion por noveno digito del RUC (P0.1 del plan de avisos).

Cubre las reglas que un aviso "declara hasta tal fecha" necesita para no
mentir: la tabla del noveno digito, el mes de declaracion, el corrimiento a dia
habil, y -- sobre todo -- los casos en que el modulo debe **negarse a dar una
fecha** en vez de estimar una.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.tax import TaxPeriod
from app.services.tax import due_dates
from app.services.tax.periods import get_or_create_period

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
# RUC sembrado por ``tests/conftest.py`` para TENANT_A; su noveno digito es 9,
# asi que el dia base de la tabla es el 26.
TENANT_A_NINTH_DIGIT_DAY = 26


def ruc_with_ninth_digit(digit: int) -> str:
    """RUC de 13 digitos cuyo noveno digito (indice 8) es ``digit``."""
    return f"17999999{digit}0001"


def context_for(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        actor_id="test",
        actor_type="SYSTEM",
        tenant_id=tenant_id,
        roles=frozenset({"scheduler"}),
        scopes=frozenset({"tax:write"}),
        token_id="test",
    )


@pytest.mark.parametrize(
    ("digit", "expected_day"),
    [(1, 10), (2, 12), (3, 14), (4, 16), (5, 18), (6, 20), (7, 22), (8, 24), (9, 26), (0, 28)],
)
def test_base_day_follows_the_ninth_digit_table(digit: int, expected_day: int) -> None:
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=6,
        ruc=ruc_with_ninth_digit(digit),
    )
    assert computed is not None
    # Se afirma sobre ``base_date`` y no sobre ``due_date`` para aislar la tabla
    # del corrimiento por fin de semana, que se prueba aparte.
    assert computed.base_date.day == expected_day
    assert computed.base_date.month == 7
    assert computed.base_date.year == 2026


def test_december_period_is_declared_the_following_january() -> None:
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=12,
        ruc=ruc_with_ninth_digit(1),
    )
    assert computed is not None
    assert computed.base_date == date(2027, 1, 10)


def test_saturday_deadline_moves_to_monday() -> None:
    # Noveno digito 2 -> 12 de septiembre de 2026, que cae sabado.
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(2),
    )
    assert computed is not None
    assert computed.base_date == date(2026, 9, 12)
    assert computed.base_date.weekday() == 5
    assert computed.due_date == date(2026, 9, 14)
    assert computed.shifted is True


def test_sunday_deadline_moves_to_monday() -> None:
    # Noveno digito 6 -> 20 de septiembre de 2026, que cae domingo.
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(6),
    )
    assert computed is not None
    assert computed.due_date == date(2026, 9, 21)
    assert computed.shifted is True


def test_weekday_deadline_is_not_shifted() -> None:
    # Noveno digito 1 -> 10 de septiembre de 2026, que cae jueves.
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(1),
    )
    assert computed is not None
    assert computed.due_date == date(2026, 9, 10)
    assert computed.shifted is False


def test_holiday_shifts_the_deadline_when_the_calendar_is_provided() -> None:
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(1),
        holidays={date(2026, 9, 10)},
    )
    assert computed is not None
    assert computed.due_date == date(2026, 9, 11)
    assert computed.shifted is True
    assert computed.holidays_checked is True


def test_holiday_run_skips_the_weekend_too() -> None:
    # Feriado el viernes 11: el corrimiento debe saltar sabado y domingo.
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(1),
        holidays={date(2026, 9, 10), date(2026, 9, 11)},
    )
    assert computed is not None
    assert computed.due_date == date(2026, 9, 14)


def test_missing_holiday_calendar_is_reported_not_assumed() -> None:
    """Sin calendario la fecha sigue siendo util, pero se marca como no verificada."""
    computed = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(1),
    )
    assert computed is not None
    assert computed.holidays_checked is False

    with_empty_calendar = due_dates.due_date_for_period(
        obligation_type="IVA",
        year=2026,
        month=8,
        ruc=ruc_with_ninth_digit(1),
        holidays=frozenset(),
    )
    assert with_empty_calendar is not None
    assert with_empty_calendar.holidays_checked is True


@pytest.mark.parametrize("obligation_type", ["ATS", "RENTA", "RDEP", "ADI"])
def test_obligations_without_a_confirmed_calendar_have_no_due_date(obligation_type: str) -> None:
    """Preferimos no dar fecha a dar una inventada (ADR 0012)."""
    assert (
        due_dates.due_date_for_period(
            obligation_type=obligation_type,
            year=2026,
            month=8,
            ruc=ruc_with_ninth_digit(1),
        )
        is None
    )


@pytest.mark.parametrize("ruc", ["", "17999", "179999999000", "17999999X0001", "  "])
def test_unusable_ruc_yields_no_due_date(ruc: str) -> None:
    assert due_dates.ninth_digit(ruc) is None
    assert (
        due_dates.due_date_for_period(
            obligation_type="IVA",
            year=2026,
            month=8,
            ruc=ruc,
        )
        is None
    )


async def test_new_iva_period_gets_its_due_date_from_the_ruc() -> None:
    context = context_for(TENANT_A)
    async with SessionFactory() as session, session.begin():
        period = await get_or_create_period(
            session,
            context,
            year=2026,
            month=8,
            obligation_type="IVA",
        )
        period_id = period.id

    async with SessionFactory() as session:
        stored = await session.scalar(select(TaxPeriod).where(TaxPeriod.id == period_id))
    assert stored is not None
    # Noveno digito 9 -> 26 de septiembre de 2026 (sabado) -> lunes 28.
    assert stored.due_date == date(2026, 9, 28)
    assert due_dates.DEADLINE_DAY_BY_NINTH_DIGIT[9] == TENANT_A_NINTH_DIGIT_DAY


async def test_explicit_due_date_is_never_overwritten() -> None:
    """Una prorroga o un regimen especial los sabe la persona, no la regla."""
    context = context_for(TENANT_A)
    async with SessionFactory() as session, session.begin():
        period = await get_or_create_period(
            session,
            context,
            year=2026,
            month=7,
            obligation_type="IVA",
            due_date=date(2026, 8, 31),
        )
        period_id = period.id

    async with SessionFactory() as session:
        stored = await session.scalar(select(TaxPeriod).where(TaxPeriod.id == period_id))
    assert stored is not None
    assert stored.due_date == date(2026, 8, 31)


async def test_period_without_a_confirmed_calendar_stays_without_due_date() -> None:
    context = context_for(TENANT_A)
    async with SessionFactory() as session, session.begin():
        period = await get_or_create_period(
            session,
            context,
            year=2026,
            month=8,
            obligation_type="ATS",
        )
        period_id = period.id

    async with SessionFactory() as session:
        stored = await session.scalar(select(TaxPeriod).where(TaxPeriod.id == period_id))
    assert stored is not None
    assert stored.due_date is None

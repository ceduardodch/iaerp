"""Pruebas de aging (Sprint 3, Fase 3: E5-05).

Cubre la funcion pura ``classify_aging_bucket`` en cada frontera exacta de
bucket con fecha de corte fija (sin depender del reloj real), el aging por
cuota (``installment_agings_for_receivable``: solo cuenta saldo abierto,
multiples cuotas en distintos buckets dentro del mismo receivable) y el
resumen por tenant (``compute_aging_summary``), ademas del endpoint HTTP
``GET /receivables/aging``.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.receivables import Receivable, ReceivableInstallment
from app.services.receivables import (
    classify_aging_bucket,
    compute_aging_summary,
    installment_agings_for_receivable,
)
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_party

_AS_OF = date(2026, 7, 10)


def _context(*, tenant_id: uuid.UUID = TENANT_A) -> AuthContext:
    return AuthContext(
        actor_id="tester@iaerp.local",
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset({"receivables:read"}),
        token_id="test-token",
    )


# --- classify_aging_bucket: funcion pura, fronteras exactas -----------------


def test_classify_aging_bucket_not_due_is_current() -> None:
    bucket, days_overdue = classify_aging_bucket(due_date=date(2026, 7, 15), as_of=_AS_OF)
    assert bucket == "CURRENT"
    assert days_overdue == 0


def test_classify_aging_bucket_due_exactly_on_cutoff_is_current() -> None:
    bucket, days_overdue = classify_aging_bucket(due_date=_AS_OF, as_of=_AS_OF)
    assert bucket == "CURRENT"
    assert days_overdue == 0


def test_classify_aging_bucket_one_day_overdue_is_1_15() -> None:
    bucket, days_overdue = classify_aging_bucket(
        due_date=_AS_OF - timedelta(days=1), as_of=_AS_OF
    )
    assert bucket == "1-15"
    assert days_overdue == 1


def test_classify_aging_bucket_lower_boundaries() -> None:
    """El limite inferior exacto de cada bucket (1, 16, 31, 61, 91 dias de mora)."""

    expectations = {
        1: "1-15",
        16: "16-30",
        31: "31-60",
        61: "61-90",
        91: "90+",
    }
    for days, expected_bucket in expectations.items():
        bucket, days_overdue = classify_aging_bucket(
            due_date=_AS_OF - timedelta(days=days), as_of=_AS_OF
        )
        assert bucket == expected_bucket, f"days={days}"
        assert days_overdue == days


def test_classify_aging_bucket_upper_boundaries() -> None:
    """El limite superior exacto de cada bucket acotado (15, 30, 60, 90 dias de mora)."""

    expectations = {
        15: "1-15",
        30: "16-30",
        60: "31-60",
        90: "61-90",
    }
    for days, expected_bucket in expectations.items():
        bucket, days_overdue = classify_aging_bucket(
            due_date=_AS_OF - timedelta(days=days), as_of=_AS_OF
        )
        assert bucket == expected_bucket, f"days={days}"
        assert days_overdue == days


def test_classify_aging_bucket_far_in_the_future_is_current() -> None:
    bucket, days_overdue = classify_aging_bucket(
        due_date=date(2027, 1, 1), as_of=_AS_OF
    )
    assert bucket == "CURRENT"
    assert days_overdue == 0


def test_classify_aging_bucket_is_deterministic_same_inputs_same_output() -> None:
    due_date = date(2026, 6, 1)
    first = classify_aging_bucket(due_date=due_date, as_of=_AS_OF)
    second = classify_aging_bucket(due_date=due_date, as_of=_AS_OF)
    assert first == second


# --- installment_agings_for_receivable: por cuota, saldo abierto -----------


async def _create_receivable_with_installments(
    *,
    suffix: str,
    due_dates_and_amounts: list[tuple[date, Decimal]],
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix=suffix)
        total = sum((amount for _, amount in due_dates_and_amounts), Decimal("0.00"))
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=total
        )
        receivable = Receivable(
            tenant_id=TENANT_A,
            sales_document_id=invoice.id,
            party_id=party.id,
            original_amount=total,
            currency="USD",
            status="OPEN",
        )
        session.add(receivable)
        await session.flush()

        installment_ids = []
        for index, (due_date, amount) in enumerate(due_dates_and_amounts, start=1):
            installment = ReceivableInstallment(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                sequence=index,
                due_date=due_date,
                amount=amount,
            )
            session.add(installment)
            await session.flush()
            installment_ids.append(installment.id)
        return receivable.id, installment_ids


async def test_installment_not_due_yet_is_current(client) -> None:
    receivable_id, _ids = await _create_receivable_with_installments(
        suffix="aging1",
        due_dates_and_amounts=[(date(2026, 8, 1), Decimal("100.00"))],
    )
    async with SessionFactory() as session:
        agings = await installment_agings_for_receivable(
            session, tenant_id=TENANT_A, receivable_id=receivable_id, as_of=_AS_OF
        )
    assert len(agings) == 1
    assert agings[0].bucket == "CURRENT"
    assert agings[0].days_overdue == 0
    assert agings[0].open_amount == Decimal("100.00")


async def test_multiple_installments_in_different_buckets(client) -> None:
    """Una factura con 3 cuotas: una vencida, dos vigentes (mismo caso del dataset)."""

    receivable_id, ids = await _create_receivable_with_installments(
        suffix="aging2",
        due_dates_and_amounts=[
            (_AS_OF - timedelta(days=20), Decimal("30.00")),  # 16-30
            (_AS_OF + timedelta(days=10), Decimal("30.00")),  # CURRENT
            (_AS_OF + timedelta(days=40), Decimal("40.00")),  # CURRENT
        ],
    )
    async with SessionFactory() as session:
        agings = await installment_agings_for_receivable(
            session, tenant_id=TENANT_A, receivable_id=receivable_id, as_of=_AS_OF
        )
    by_installment = {aging.installment_id: aging for aging in agings}
    assert by_installment[ids[0]].bucket == "16-30"
    assert by_installment[ids[1]].bucket == "CURRENT"
    assert by_installment[ids[2]].bucket == "CURRENT"


async def test_partially_paid_installment_only_counts_open_balance(client) -> None:
    from app.models.receivables import Movement

    receivable_id, ids = await _create_receivable_with_installments(
        suffix="aging3",
        due_dates_and_amounts=[(_AS_OF - timedelta(days=45), Decimal("100.00"))],
    )
    async with SessionFactory() as session, session.begin():
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable_id,
                installment_id=ids[0],
                movement_type="PAYMENT",
                amount=Decimal("70.00"),
                actor_id="tester@iaerp.local",
            )
        )

    async with SessionFactory() as session:
        agings = await installment_agings_for_receivable(
            session, tenant_id=TENANT_A, receivable_id=receivable_id, as_of=_AS_OF
        )
    assert len(agings) == 1
    assert agings[0].open_amount == Decimal("30.00")
    assert agings[0].bucket == "31-60"


async def test_fully_paid_installment_is_excluded_from_aging(client) -> None:
    from app.models.receivables import Movement

    receivable_id, ids = await _create_receivable_with_installments(
        suffix="aging4",
        due_dates_and_amounts=[(_AS_OF - timedelta(days=100), Decimal("50.00"))],
    )
    async with SessionFactory() as session, session.begin():
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable_id,
                installment_id=ids[0],
                movement_type="PAYMENT",
                amount=Decimal("50.00"),
                actor_id="tester@iaerp.local",
            )
        )

    async with SessionFactory() as session:
        agings = await installment_agings_for_receivable(
            session, tenant_id=TENANT_A, receivable_id=receivable_id, as_of=_AS_OF
        )
    assert agings == []


# --- compute_aging_summary: agregado por tenant y por cliente --------------


async def test_aging_summary_is_reproducible_with_fixed_as_of(client) -> None:
    await _create_receivable_with_installments(
        suffix="aging5",
        due_dates_and_amounts=[
            (_AS_OF - timedelta(days=5), Decimal("25.00")),
            (_AS_OF - timedelta(days=25), Decimal("15.00")),
        ],
    )

    async with SessionFactory() as session:
        first = await compute_aging_summary(session, _context(), as_of=_AS_OF)
    async with SessionFactory() as session:
        second = await compute_aging_summary(session, _context(), as_of=_AS_OF)

    assert first.as_of == second.as_of == _AS_OF
    first_totals = {bucket.bucket: bucket.total for bucket in first.buckets}
    second_totals = {bucket.bucket: bucket.total for bucket in second.buckets}
    assert first_totals == second_totals
    assert first_totals["1-15"] == Decimal("25.00")
    assert first_totals["16-30"] == Decimal("15.00")


async def test_aging_summary_groups_by_party(client) -> None:
    receivable_id, ids = await _create_receivable_with_installments(
        suffix="aging6",
        due_dates_and_amounts=[(_AS_OF - timedelta(days=2), Decimal("12.00"))],
    )
    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        party_id = entity.party_id

    async with SessionFactory() as session:
        summary = await compute_aging_summary(session, _context(), as_of=_AS_OF)

    matching = [row for row in summary.by_party if row.party_id == party_id]
    assert len(matching) == 1
    assert matching[0].bucket == "1-15"
    assert matching[0].total == Decimal("12.00")


async def test_get_receivables_aging_endpoint_with_fixed_as_of(client) -> None:
    await _create_receivable_with_installments(
        suffix="aging7",
        due_dates_and_amounts=[(_AS_OF - timedelta(days=95), Decimal("18.00"))],
    )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.get(
        "/api/v1/receivables/aging",
        headers=auth(token),
        params={"asOf": _AS_OF.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["asOf"] == _AS_OF.isoformat()
    bucket_totals = {row["bucket"]: row["total"] for row in body["buckets"]}
    assert bucket_totals["90+"] == "18.00"


async def test_get_receivable_detail_includes_worst_aging_bucket(client) -> None:
    receivable_id, _ids = await _create_receivable_with_installments(
        suffix="aging8",
        due_dates_and_amounts=[
            (_AS_OF - timedelta(days=3), Decimal("10.00")),
            (_AS_OF - timedelta(days=70), Decimal("10.00")),
        ],
    )
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.get(
        f"/api/v1/receivables/{receivable_id}",
        headers=auth(token),
        params={"asOf": _AS_OF.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The worst (most overdue) open installment wins the receivable-level bucket.
    assert body["aging"]["bucket"] == "61-90"
    assert body["aging"]["daysOverdue"] == 70

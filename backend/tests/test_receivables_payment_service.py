"""Unitarias de Receivables (Sprint 3, Fase 2: E5-03/E5-04/E5-08).

Cubre ``services/receivables.py::record_payment``/``apply_credit_note`` a
nivel de servicio (sin HTTP): asignacion oldest-first, saldo exacto/parcial,
sobreaplicacion rechazada con 422 y saldo nunca negativo, retenciones y
descuentos con su propio ``movement_type``, aplicacion de nota de credito con
excedente a ``CustomerCredit``, e idempotencia de ``apply_credit_note`` por
``access_key``.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.receivables import CustomerCredit, Movement, Receivable, ReceivableInstallment
from app.schemas.receivables import DiscountInput, PaymentInput, RetentionInput
from app.services.receivables import (
    apply_credit_note,
    compute_receivable_balance,
    lock_receivable,
    record_payment,
)
from tests.test_billing_api import TENANT_A
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_party

_sequential_counter = itertools.count(2000)


def _context(*, tenant_id: uuid.UUID, actor_id: str = "tester@iaerp.local") -> AuthContext:
    return AuthContext(
        actor_id=actor_id,
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset({"receivables:write"}),
        token_id="test-token",
    )


async def _create_receivable(
    session,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID,
    sales_document_id: uuid.UUID,
    original_amount: Decimal,
    installment_amounts: list[Decimal],
    due_date: date,
) -> tuple[Receivable, list[ReceivableInstallment]]:
    receivable = Receivable(
        tenant_id=tenant_id,
        sales_document_id=sales_document_id,
        party_id=party_id,
        original_amount=original_amount,
        currency="USD",
        status="OPEN",
    )
    session.add(receivable)
    await session.flush()

    installments = []
    for index, amount in enumerate(installment_amounts, start=1):
        installment = ReceivableInstallment(
            tenant_id=tenant_id,
            receivable_id=receivable.id,
            sequence=index,
            due_date=due_date,
            amount=amount,
        )
        session.add(installment)
        installments.append(installment)
    await session.flush()
    return receivable, installments


async def _setup_single_installment_receivable(
    *, suffix: str, total: Decimal, due_date: date = date(2026, 8, 1)
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix=suffix)
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=total
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=total,
            installment_amounts=[total],
            due_date=due_date,
        )
        return receivable.id


async def test_record_payment_exact_amount_settles_receivable(client) -> None:
    receivable_id = await _setup_single_installment_receivable(
        suffix="pay1", total=Decimal("100.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("100.00"), payment_date=date(2026, 7, 10))

    async with SessionFactory() as session, session.begin():
        summary = await record_payment(
            session,
            context,
            receivable_id,
            payment,
            correlation_id=str(uuid.uuid4()),
            idempotency_key="pay-exact-0001",
        )

    assert summary.open_amount == Decimal("0.00")
    assert summary.status == "SETTLED"

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        assert entity.status == "PAID"
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(Movement.receivable_id == receivable_id)
                )
            ).all()
        )
        assert len(movements) == 1
        assert movements[0].movement_type == "PAYMENT"
        assert movements[0].amount == Decimal("100.00")


async def test_record_payment_partial_amount_leaves_open_balance(client) -> None:
    receivable_id = await _setup_single_installment_receivable(
        suffix="pay2", total=Decimal("100.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("40.00"), payment_date=date(2026, 7, 10))

    async with SessionFactory() as session, session.begin():
        summary = await record_payment(
            session,
            context,
            receivable_id,
            payment,
            correlation_id=str(uuid.uuid4()),
            idempotency_key="pay-partial-0001",
        )

    assert summary.open_amount == Decimal("60.00")
    assert summary.status == "PARTIAL"

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        assert entity.status == "PARTIALLY_PAID"


async def test_record_payment_overapplication_is_rejected_and_balance_untouched(client) -> None:
    receivable_id = await _setup_single_installment_receivable(
        suffix="pay3", total=Decimal("50.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("50.01"), payment_date=date(2026, 7, 10))

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await record_payment(
                session,
                context,
                receivable_id,
                payment,
                correlation_id=str(uuid.uuid4()),
                idempotency_key="pay-over-0001",
            )
    assert exc_info.value.status_code == 422

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
    assert balance == Decimal("50.00")
    assert entity.status == "OPEN"


async def test_record_payment_never_leaves_negative_balance_at_exact_limit(client) -> None:
    """El limite exacto (saldo llega a 0.00) SI se permite; nunca queda negativo."""

    receivable_id = await _setup_single_installment_receivable(
        suffix="pay4", total=Decimal("25.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("25.00"), payment_date=date(2026, 7, 10))

    async with SessionFactory() as session, session.begin():
        summary = await record_payment(
            session,
            context,
            receivable_id,
            payment,
            correlation_id=str(uuid.uuid4()),
            idempotency_key="pay-limit-0001",
        )
    assert summary.open_amount == Decimal("0.00")


async def test_record_payment_rejects_zero_total(client) -> None:
    receivable_id = await _setup_single_installment_receivable(
        suffix="pay5", total=Decimal("10.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("0.00"), payment_date=date(2026, 7, 10))

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await record_payment(
                session,
                context,
                receivable_id,
                payment,
                correlation_id=str(uuid.uuid4()),
                idempotency_key="pay-zero-0001",
            )
    assert exc_info.value.status_code == 422


async def test_record_payment_with_retention_and_discount_reduces_balance_by_type(client) -> None:
    receivable_id = await _setup_single_installment_receivable(
        suffix="pay6", total=Decimal("100.00")
    )
    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(
        cash_amount=Decimal("60.00"),
        payment_date=date(2026, 7, 10),
        retentions=[
            RetentionInput(kind="RETENTION_IVA", amount=Decimal("10.00"), reason="Retencion IVA")
        ],
        discounts=[DiscountInput(amount=Decimal("5.00"), reason="Pronto pago")],
    )

    async with SessionFactory() as session, session.begin():
        summary = await record_payment(
            session,
            context,
            receivable_id,
            payment,
            correlation_id=str(uuid.uuid4()),
            idempotency_key="pay-retdisc-0001",
        )

    # 100 - (60 + 10 + 5) = 25
    assert summary.open_amount == Decimal("25.00")

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(Movement.receivable_id == receivable_id)
                )
            ).all()
        )
    by_type = {movement.movement_type: movement.amount for movement in movements}
    assert by_type["PAYMENT"] == Decimal("60.00")
    assert by_type["RETENTION"] == Decimal("10.00")
    assert by_type["DISCOUNT"] == Decimal("5.00")


async def test_record_payment_applies_to_oldest_installment_first(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="pay7")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("150.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("150.00"),
            installment_amounts=[Decimal("50.00"), Decimal("50.00"), Decimal("50.00")],
            due_date=date(2026, 8, 1),
        )
        # Force distinct due dates so oldest-first ordering is unambiguous.
        installments[0].due_date = date(2026, 8, 1)
        installments[1].due_date = date(2026, 9, 1)
        installments[2].due_date = date(2026, 10, 1)
        receivable_id = receivable.id
        installment_ids = [installment.id for installment in installments]

    context = _context(tenant_id=TENANT_A)
    payment = PaymentInput(cash_amount=Decimal("70.00"), payment_date=date(2026, 7, 10))

    async with SessionFactory() as session, session.begin():
        await record_payment(
            session,
            context,
            receivable_id,
            payment,
            correlation_id=str(uuid.uuid4()),
            idempotency_key="pay-oldest-0001",
        )

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(Movement.receivable_id == receivable_id)
                )
            ).all()
        )
    applied_by_installment = {movement.installment_id: movement.amount for movement in movements}
    # 70 applied oldest-first: 50 to installment[0] (fully settled), 20 to installment[1].
    assert applied_by_installment[installment_ids[0]] == Decimal("50.00")
    assert applied_by_installment[installment_ids[1]] == Decimal("20.00")
    assert installment_ids[2] not in applied_by_installment


async def _authorized_credit_note_stub(
    session, *, tenant_id: uuid.UUID, party_id: uuid.UUID, total: Decimal, access_key: str
):
    from app.models.billing import SalesDocument

    sequential = f"{next(_sequential_counter):09d}"
    document = SalesDocument(
        tenant_id=tenant_id,
        document_type="CREDIT_NOTE",
        establishment_id=(await _existing_establishment(session, tenant_id)).id,
        emission_point_id=(await _existing_emission_point(session, tenant_id)).id,
        sequential=sequential,
        access_key=access_key,
        party_id=party_id,
        issue_date=date(2026, 7, 4),
        status="AUTHORIZED",
        currency="USD",
        subtotal=total,
        tax_total=Decimal("0.00"),
        total=total,
        fiscal_policy_version="ec-iva-v1",
        authorization_number=access_key,
    )
    session.add(document)
    await session.flush()
    return document


async def _existing_establishment(session, tenant_id):
    from app.models.masters import Establishment

    establishment = await session.scalar(
        select(Establishment).where(Establishment.tenant_id == tenant_id).limit(1)
    )
    assert establishment is not None
    return establishment


async def _existing_emission_point(session, tenant_id):
    from app.models.masters import EmissionPoint

    emission_point = await session.scalar(
        select(EmissionPoint).where(EmissionPoint.tenant_id == tenant_id).limit(1)
    )
    assert emission_point is not None
    return emission_point


async def test_apply_credit_note_within_balance_settles_partially(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="cn1")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("100.00")],
            due_date=date(2026, 8, 1),
        )
        receivable_id = receivable.id
        party_id = party.id

    access_key = "9" * 49
    async with SessionFactory() as session, session.begin():
        credit_note = await _authorized_credit_note_stub(
            session,
            tenant_id=TENANT_A,
            party_id=party_id,
            total=Decimal("40.00"),
            access_key=access_key,
        )
        locked = await lock_receivable(session, tenant_id=TENANT_A, receivable_id=receivable_id)
        movement = await apply_credit_note(
            session,
            tenant_id=TENANT_A,
            receivable=locked,
            credit_note_total=Decimal("40.00"),
            credit_note_access_key=access_key,
            party_id=party_id,
            origin_credit_note_id=credit_note.id,
            actor_id="system:test",
        )
        assert movement is not None
        assert movement.movement_type == "CREDIT_NOTE"

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
        assert balance == Decimal("60.00")
        assert entity.status == "PARTIALLY_PAID"
        credit_rows = list(
            (
                await session.scalars(
                    select(CustomerCredit).where(CustomerCredit.party_id == party_id)
                )
            ).all()
        )
        assert credit_rows == []


async def test_apply_credit_note_at_exact_limit_settles_without_customer_credit(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="cn2")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("70.00")
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("70.00"),
            installment_amounts=[Decimal("70.00")],
            due_date=date(2026, 8, 1),
        )
        receivable_id = receivable.id
        party_id = party.id

    access_key = "8" * 49
    async with SessionFactory() as session, session.begin():
        credit_note = await _authorized_credit_note_stub(
            session,
            tenant_id=TENANT_A,
            party_id=party_id,
            total=Decimal("70.00"),
            access_key=access_key,
        )
        locked = await lock_receivable(session, tenant_id=TENANT_A, receivable_id=receivable_id)
        await apply_credit_note(
            session,
            tenant_id=TENANT_A,
            receivable=locked,
            credit_note_total=Decimal("70.00"),
            credit_note_access_key=access_key,
            party_id=party_id,
            origin_credit_note_id=credit_note.id,
            actor_id="system:test",
        )

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
        assert balance == Decimal("0.00")
        assert entity.status == "PAID"


async def test_apply_credit_note_with_surplus_creates_customer_credit(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="cn3")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("30.00")
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("30.00"),
            installment_amounts=[Decimal("30.00")],
            due_date=date(2026, 8, 1),
        )
        receivable_id = receivable.id
        party_id = party.id

    access_key = "7" * 49
    async with SessionFactory() as session, session.begin():
        credit_note = await _authorized_credit_note_stub(
            session,
            tenant_id=TENANT_A,
            party_id=party_id,
            total=Decimal("50.00"),
            access_key=access_key,
        )
        locked = await lock_receivable(session, tenant_id=TENANT_A, receivable_id=receivable_id)
        await apply_credit_note(
            session,
            tenant_id=TENANT_A,
            receivable=locked,
            credit_note_total=Decimal("50.00"),
            credit_note_access_key=access_key,
            party_id=party_id,
            origin_credit_note_id=credit_note.id,
            actor_id="system:test",
        )

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
        assert balance == Decimal("0.00")
        assert entity.status == "PAID"
        credit = await session.scalar(
            select(CustomerCredit).where(CustomerCredit.origin_credit_note_id == credit_note.id)
        )
        assert credit is not None
        assert credit.amount == Decimal("20.00")
        assert credit.remaining_amount == Decimal("20.00")


async def test_apply_credit_note_is_idempotent_by_access_key(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="cn4")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("40.00")
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("40.00"),
            installment_amounts=[Decimal("40.00")],
            due_date=date(2026, 8, 1),
        )
        receivable_id = receivable.id
        party_id = party.id

    access_key = "6" * 49
    async with SessionFactory() as session, session.begin():
        credit_note = await _authorized_credit_note_stub(
            session,
            tenant_id=TENANT_A,
            party_id=party_id,
            total=Decimal("15.00"),
            access_key=access_key,
        )
        credit_note_id = credit_note.id

    for _ in range(2):
        async with SessionFactory() as session, session.begin():
            locked = await lock_receivable(session, tenant_id=TENANT_A, receivable_id=receivable_id)
            await apply_credit_note(
                session,
                tenant_id=TENANT_A,
                receivable=locked,
                credit_note_total=Decimal("15.00"),
                credit_note_access_key=access_key,
                party_id=party_id,
                origin_credit_note_id=credit_note_id,
                actor_id="system:test",
            )

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(
                        Movement.receivable_id == receivable_id,
                        Movement.movement_type == "CREDIT_NOTE",
                    )
                )
            ).all()
        )
        assert len(movements) == 1
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
    assert balance == Decimal("25.00")

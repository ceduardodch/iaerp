"""Unitarias de Receivables (Sprint 3, Fase 1: E5-01/E5-02).

Cubre el invariante 11 del dominio ("cuotas... suman exactamente el monto
original") y el calculo de saldo on-demand (``compute_installment_balance``/
``compute_receivable_balance``) bajo combinaciones de ``Movement`` activos y
revertidos, sin depender de HTTP ni del worker de eventos.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.masters import Party
from app.models.receivables import Movement, Receivable, ReceivableInstallment
from app.services.receivables import (
    compute_installment_balance,
    compute_receivable_balance,
)
from tests.test_billing_api import TENANT_A

_sequential_counter = itertools.count(950)


async def _create_party(session, *, tenant_id: uuid.UUID, suffix: str) -> Party:
    party = Party(
        tenant_id=tenant_id,
        name=f"Cliente {suffix}",
        identification_type="CEDULA",
        identification_number=f"179000{suffix}",
        roles=["CUSTOMER"],
    )
    session.add(party)
    await session.flush()
    return party


async def _create_authorized_invoice_stub(
    session, *, tenant_id: uuid.UUID, party_id: uuid.UUID, total: Decimal
) -> SalesDocument:
    """Factura AUTHORIZED minima: solo lo que ``Receivable.sales_document_id``
    necesita para satisfacer su ``ForeignKeyConstraint`` compuesta
    ``(tenant_id, sales_document_id)``. Estas pruebas ejercitan el calculo de
    saldo, no el pipeline de emision, asi que no requieren establishment/
    emission point/lineas reales.
    """

    from app.models.masters import EmissionPoint, Establishment

    establishment = await session.scalar(
        select(Establishment).where(Establishment.tenant_id == tenant_id).limit(1)
    )
    if establishment is None:
        establishment = Establishment(
            tenant_id=tenant_id, code="900", name="Fixture", address="N/A"
        )
        session.add(establishment)
        await session.flush()
    emission_point = await session.scalar(
        select(EmissionPoint)
        .where(
            EmissionPoint.tenant_id == tenant_id,
            EmissionPoint.establishment_id == establishment.id,
        )
        .limit(1)
    )
    if emission_point is None:
        emission_point = EmissionPoint(
            tenant_id=tenant_id, establishment_id=establishment.id, code="900"
        )
        session.add(emission_point)
        await session.flush()

    sequential = f"{next(_sequential_counter):09d}"
    document = SalesDocument(
        tenant_id=tenant_id,
        document_type="INVOICE",
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=sequential,
        access_key=sequential.rjust(49, "2"),
        party_id=party_id,
        issue_date=date(2026, 7, 4),
        status="AUTHORIZED",
        currency="USD",
        subtotal=total,
        tax_total=Decimal("0.00"),
        total=total,
        fiscal_policy_version="ec-iva-v1",
        authorization_number=sequential.rjust(49, "2"),
    )
    session.add(document)
    await session.flush()
    return document


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


async def test_installment_amounts_summing_to_original_amount_is_the_valid_shape(client) -> None:
    """Documenta el invariante 11: 3 cuotas que suman exactamente el original."""

    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="1")
        original_amount = Decimal("115.00")
        installment_amounts = [Decimal("40.00"), Decimal("40.00"), Decimal("35.00")]
        assert sum(installment_amounts, Decimal("0.00")) == original_amount
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=original_amount
        )

        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=original_amount,
            installment_amounts=installment_amounts,
            due_date=date(2026, 8, 1),
        )
        assert len(installments) == 3

    async with SessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(ReceivableInstallment).where(
                        ReceivableInstallment.receivable_id == receivable.id
                    )
                )
            ).all()
        )
        assert sum((row.amount for row in rows), Decimal("0.00")) == original_amount


async def test_compute_installment_balance_with_no_movements_equals_full_amount(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="2")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        _, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("100.00")],
            due_date=date(2026, 8, 1),
        )
        installment = installments[0]

    async with SessionFactory() as session:
        balance = await compute_installment_balance(
            session, tenant_id=TENANT_A, installment=installment
        )
    assert balance == Decimal("100.00")


async def test_compute_installment_balance_combines_payment_retention_and_discount(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="3")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("100.00")],
            due_date=date(2026, 8, 1),
        )
        installment = installments[0]
        session.add_all(
            [
                Movement(
                    tenant_id=TENANT_A,
                    receivable_id=receivable.id,
                    installment_id=installment.id,
                    movement_type="PAYMENT",
                    amount=Decimal("60.00"),
                    actor_id="tester",
                ),
                Movement(
                    tenant_id=TENANT_A,
                    receivable_id=receivable.id,
                    installment_id=installment.id,
                    movement_type="RETENTION",
                    amount=Decimal("10.00"),
                    actor_id="tester",
                ),
                Movement(
                    tenant_id=TENANT_A,
                    receivable_id=receivable.id,
                    installment_id=installment.id,
                    movement_type="DISCOUNT",
                    amount=Decimal("5.00"),
                    actor_id="tester",
                ),
            ]
        )

    async with SessionFactory() as session:
        balance = await compute_installment_balance(
            session, tenant_id=TENANT_A, installment=installment
        )
    # 100.00 - (60.00 payment + 10.00 retention + 5.00 discount) = 25.00
    assert balance == Decimal("25.00")


async def test_compute_installment_balance_reaches_exact_zero(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="4")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("50.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("50.00"),
            installment_amounts=[Decimal("50.00")],
            due_date=date(2026, 8, 1),
        )
        installment = installments[0]
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                installment_id=installment.id,
                movement_type="PAYMENT",
                amount=Decimal("50.00"),
                actor_id="tester",
            )
        )

    async with SessionFactory() as session:
        balance = await compute_installment_balance(
            session, tenant_id=TENANT_A, installment=installment
        )
    assert balance == Decimal("0.00")


async def test_compute_installment_balance_excludes_reversed_movement(client) -> None:
    """Un PAYMENT revertido no debe reducir el saldo (el REVERSAL lo deshace)."""

    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="5")
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("80.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("80.00"),
            installment_amounts=[Decimal("80.00")],
            due_date=date(2026, 8, 1),
        )
        installment = installments[0]
        payment = Movement(
            tenant_id=TENANT_A,
            receivable_id=receivable.id,
            installment_id=installment.id,
            movement_type="PAYMENT",
            amount=Decimal("30.00"),
            actor_id="tester",
        )
        session.add(payment)
        await session.flush()
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                installment_id=installment.id,
                movement_type="REVERSAL",
                amount=Decimal("30.00"),
                actor_id="tester",
                reversed_movement_id=payment.id,
            )
        )

    async with SessionFactory() as session:
        balance = await compute_installment_balance(
            session, tenant_id=TENANT_A, installment=installment
        )
    # The reverted PAYMENT no longer counts against the balance.
    assert balance == Decimal("80.00")


async def test_compute_receivable_balance_sums_all_installments(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="6")
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
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                installment_id=installments[0].id,
                movement_type="PAYMENT",
                amount=Decimal("50.00"),
                actor_id="tester",
            )
        )

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable.id)
        assert entity is not None
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)
    # 0 (first installment fully paid) + 50 + 50
    assert balance == Decimal("100.00")


@pytest.mark.parametrize(
    ("payment_amount", "expected_balance"),
    [
        (Decimal("99.99"), Decimal("0.01")),
        (Decimal("100.00"), Decimal("0.00")),
    ],
)
async def test_compute_installment_balance_precision_at_the_boundary(
    client, payment_amount, expected_balance
) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(
            session, tenant_id=TENANT_A, suffix=f"7{payment_amount}".replace(".", "")[:6]
        )
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("100.00")],
            due_date=date(2026, 8, 1),
        )
        installment = installments[0]
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                installment_id=installment.id,
                movement_type="PAYMENT",
                amount=payment_amount,
                actor_id="tester",
            )
        )

    async with SessionFactory() as session:
        balance = await compute_installment_balance(
            session, tenant_id=TENANT_A, installment=installment
        )
    assert balance == expected_balance

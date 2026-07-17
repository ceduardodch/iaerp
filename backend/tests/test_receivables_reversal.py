"""Pruebas de reverso de movimiento (Sprint 3, Fase 3: E5-09).

Cubre ``services/receivables.py::reverse_movement`` a nivel de servicio
(revertir un PAYMENT libera exactamente el monto revertido, revertir un
REVERSAL se rechaza, un movimiento ya revertido no admite un segundo
reverso, el original queda intacto, el efecto sobre CustomerCredit al
revertir un CREDIT_NOTE con excedente) y el endpoint HTTP
``POST /receivables/{id}/movements/{movementId}/reversal`` (idempotencia,
scope, tenant, auditoria, ciclo cobro -> reverso -> saldo vuelve al previo).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.platform import AuditEvent
from app.models.receivables import CustomerCredit, Movement, Receivable
from app.schemas.receivables import PaymentInput
from app.services.receivables import (
    apply_credit_note,
    compute_receivable_balance,
    lock_receivable,
    record_payment,
    reverse_movement,
)
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for
from tests.test_receivables_payment_service import _authorized_credit_note_stub, _create_receivable
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_party


def _context(
    *, tenant_id: uuid.UUID = TENANT_A, actor_id: str = "tester@iaerp.local"
) -> AuthContext:
    return AuthContext(
        actor_id=actor_id,
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset({"receivables:write"}),
        token_id="test-token",
    )


async def _setup_receivable_with_payment(
    *, suffix: str, total: Decimal, cash_amount: Decimal
) -> tuple[uuid.UUID, uuid.UUID]:
    """Receivable de una cuota con un PAYMENT ya aplicado. Devuelve (receivable_id, movement_id)."""

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
            due_date=date(2026, 8, 1),
        )
        receivable_id = receivable.id

    async with SessionFactory() as session, session.begin():
        await record_payment(
            session,
            _context(),
            receivable_id,
            PaymentInput(cash_amount=cash_amount, payment_date=date(2026, 7, 10)),
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"setup-payment-{suffix}",
        )

    async with SessionFactory() as session:
        movement = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == receivable_id, Movement.movement_type == "PAYMENT"
            )
        )
        assert movement is not None
        return receivable_id, movement.id


# --- reverse_movement: servicio ---------------------------------------------


async def test_reverse_payment_releases_exactly_the_reversed_amount(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev1", total=Decimal("100.00"), cash_amount=Decimal("40.00")
    )

    async with SessionFactory() as session:
        entity = await session.get(Receivable, receivable_id)
        balance_before = await compute_receivable_balance(
            session, tenant_id=TENANT_A, receivable=entity
        )
    assert balance_before == Decimal("60.00")

    async with SessionFactory() as session, session.begin():
        summary = await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason="Cobro duplicado por error",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-service-0001",
        )

    # 60.00 open + 40.00 released by the reversal = 100.00 (fully open again).
    assert summary.open_amount == Decimal("100.00")
    assert summary.status == "OPEN"

    async with SessionFactory() as session:
        movements = list(
            (
                await session.scalars(
                    select(Movement).where(Movement.receivable_id == receivable_id)
                )
            ).all()
        )
    assert len(movements) == 2
    original = next(m for m in movements if m.movement_type == "PAYMENT")
    reversal = next(m for m in movements if m.movement_type == "REVERSAL")
    assert original.amount == Decimal("40.00")  # original untouched
    assert reversal.amount == Decimal("40.00")
    assert reversal.reversed_movement_id == original.id
    assert reversal.support_reference == "Cobro duplicado por error"


async def test_reverse_a_reversal_is_rejected(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev2", total=Decimal("50.00"), cash_amount=Decimal("20.00")
    )

    async with SessionFactory() as session, session.begin():
        await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason="Correccion",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-chain-0001",
        )

    async with SessionFactory() as session:
        reversal = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == receivable_id, Movement.movement_type == "REVERSAL"
            )
        )
        reversal_id = reversal.id

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await reverse_movement(
                session,
                _context(),
                receivable_id=receivable_id,
                movement_id=reversal_id,
                reason="Intento invalido",
                correlation_id=str(uuid.uuid4()),
                idempotency_key="rev-chain-0002",
            )
    assert exc_info.value.status_code == 422


async def test_reverse_an_already_reversed_movement_is_rejected(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev3", total=Decimal("30.00"), cash_amount=Decimal("30.00")
    )

    async with SessionFactory() as session, session.begin():
        await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason="Primer reverso",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-twice-0001",
        )

    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await reverse_movement(
                session,
                _context(),
                receivable_id=receivable_id,
                movement_id=movement_id,
                reason="Segundo intento, debe fallar",
                correlation_id=str(uuid.uuid4()),
                idempotency_key="rev-twice-0002",
            )
    assert exc_info.value.status_code == 422


async def test_original_movement_stays_intact_after_reversal(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev4", total=Decimal("80.00"), cash_amount=Decimal("35.00")
    )

    async with SessionFactory() as session:
        original_before = await session.get(Movement, movement_id)
        original_amount_before = original_before.amount
        original_type_before = original_before.movement_type
        original_installment_before = original_before.installment_id

    async with SessionFactory() as session, session.begin():
        await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason="Verificar inmutabilidad del original",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-intact-0001",
        )

    async with SessionFactory() as session:
        original_after = await session.get(Movement, movement_id)
        assert original_after.amount == original_amount_before
        assert original_after.movement_type == original_type_before
        assert original_after.installment_id == original_installment_before


async def test_reverse_movement_not_found_returns_404(client) -> None:
    receivable_id, _movement_id = await _setup_receivable_with_payment(
        suffix="rev5", total=Decimal("20.00"), cash_amount=Decimal("10.00")
    )
    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await reverse_movement(
                session,
                _context(),
                receivable_id=receivable_id,
                movement_id=uuid.uuid4(),
                reason="Movimiento inexistente",
                correlation_id=str(uuid.uuid4()),
                idempotency_key="rev-missing-0001",
            )
    assert exc_info.value.status_code == 404


async def test_reverse_movement_respects_tenant_scope(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev6", total=Decimal("15.00"), cash_amount=Decimal("15.00")
    )
    with pytest.raises(HTTPException) as exc_info:
        async with SessionFactory() as session, session.begin():
            await reverse_movement(
                session,
                _context(tenant_id=TENANT_B),
                receivable_id=receivable_id,
                movement_id=movement_id,
                reason="Cross-tenant, debe fallar",
                correlation_id=str(uuid.uuid4()),
                idempotency_key="rev-tenant-0001",
            )
    assert exc_info.value.status_code == 404


async def test_reverse_movement_audits_with_reason_and_original_id(client) -> None:
    receivable_id, movement_id = await _setup_receivable_with_payment(
        suffix="rev7", total=Decimal("60.00"), cash_amount=Decimal("25.00")
    )

    async with SessionFactory() as session, session.begin():
        await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason="Retencion mal calculada",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-audit-0001",
        )

    async with SessionFactory() as session:
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == TENANT_A, AuditEvent.action == "movement.reversed"
            )
        )
    assert event is not None
    assert event.details["original_movement_id"] == str(movement_id)
    assert event.details["reason"] == "Retencion mal calculada"


async def test_reverse_credit_note_movement_reduces_customer_credit_surplus(client) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix="rev8")
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

    access_key = "5" * 49
    async with SessionFactory() as session, session.begin():
        credit_note = await _authorized_credit_note_stub(
            session,
            tenant_id=TENANT_A,
            party_id=party_id,
            total=Decimal("50.00"),
            access_key=access_key,
        )
        locked = await lock_receivable(session, tenant_id=TENANT_A, receivable_id=receivable_id)
        movement = await apply_credit_note(
            session,
            tenant_id=TENANT_A,
            receivable=locked,
            credit_note_total=Decimal("50.00"),
            credit_note_access_key=access_key,
            party_id=party_id,
            origin_credit_note_id=credit_note.id,
            actor_id="system:test",
        )
        credit_note_movement_id = movement.id

    async with SessionFactory() as session:
        credit = await session.scalar(
            select(CustomerCredit).where(CustomerCredit.origin_credit_note_id == credit_note.id)
        )
        assert credit.remaining_amount == Decimal("20.00")

    async with SessionFactory() as session, session.begin():
        await reverse_movement(
            session,
            _context(),
            receivable_id=receivable_id,
            movement_id=credit_note_movement_id,
            reason="NC aplicada por error",
            correlation_id=str(uuid.uuid4()),
            idempotency_key="rev-cn-0001",
        )

    async with SessionFactory() as session:
        credit_after = await session.scalar(
            select(CustomerCredit).where(CustomerCredit.origin_credit_note_id == credit_note.id)
        )
        entity = await session.get(Receivable, receivable_id)
        balance = await compute_receivable_balance(session, tenant_id=TENANT_A, receivable=entity)

    # The 30.00 receivable balance is reopened (CREDIT_NOTE movement undone)...
    assert balance == Decimal("30.00")
    # ...and the surplus CustomerCredit it had generated is reduced to zero.
    assert credit_after.remaining_amount == Decimal("0.00")
    assert credit_after.amount == Decimal("0.00")


# --- endpoint HTTP: idempotencia, scope, ciclo cobro -> reverso -------------


async def _create_receivable_via_event_http(
    *, key_prefix: str, sequential: str, total: Decimal
) -> str:
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.workers.receivables import handle_invoice_authorized
    from tests.test_billing_api import _setup_billing_masters
    from tests.test_receivables_flow import _insert_authorized_invoice, _message_for

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api_client:
        token = await token_for(
            api_client,
            "a@iaerp.local",
            TENANT_A,
            ["organization:write", "organization:read", "parties:write", "products:write"],
        )
        masters = await _setup_billing_masters(api_client, token, key_prefix=key_prefix)
        document = await _insert_authorized_invoice(
            tenant_id=TENANT_A,
            establishment_id=uuid.UUID(masters["establishment_id"]),
            emission_point_id=uuid.UUID(masters["emission_point_id"]),
            party_id=uuid.UUID(masters["party_id"]),
            product_id=uuid.UUID(masters["product_id"]),
            sequential=sequential,
            total=total,
            issue_date=date(2026, 12, 1),
        )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()
    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document.id)
        )
    return str(receivable.id)


async def test_reverse_movement_via_api_updates_open_amount(client) -> None:
    receivable_id = await _create_receivable_via_event_http(
        key_prefix="api-rev1", sequential="000000950", total=Decimal("100.00")
    )
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    payment_response = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "rev-api-pay-0001"),
        json={
            "cashAmount": "40.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    assert payment_response.status_code == 201, payment_response.text

    async with SessionFactory() as session:
        movement = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == uuid.UUID(receivable_id),
                Movement.movement_type == "PAYMENT",
            )
        )
        movement_id = movement.id

    reversal_response = await client.post(
        f"/api/v1/receivables/{receivable_id}/movements/{movement_id}/reversal",
        headers=auth(token, "rev-api-0001-0001"),
        json={"reason": "Cobro registrado por error"},
    )
    assert reversal_response.status_code == 201, reversal_response.text
    body = reversal_response.json()
    assert body["openAmount"] == "100.00"
    assert body["status"] == "OPEN"


async def test_reverse_movement_idempotency_key_replay_does_not_duplicate(client) -> None:
    receivable_id = await _create_receivable_via_event_http(
        key_prefix="api-rev2", sequential="000000951", total=Decimal("70.00")
    )
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "rev-api-pay-0002"),
        json={
            "cashAmount": "70.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    async with SessionFactory() as session:
        movement = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == uuid.UUID(receivable_id),
                Movement.movement_type == "PAYMENT",
            )
        )
        movement_id = movement.id

    payload = {"reason": "Reintento con la misma clave"}
    first = await client.post(
        f"/api/v1/receivables/{receivable_id}/movements/{movement_id}/reversal",
        headers=auth(token, "rev-api-idem-0001"),
        json=payload,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/api/v1/receivables/{receivable_id}/movements/{movement_id}/reversal",
        headers=auth(token, "rev-api-idem-0001"),
        json=payload,
    )
    assert second.status_code == 201, second.text
    assert first.json() == second.json()

    async with SessionFactory() as session:
        reversals = list(
            (
                await session.scalars(
                    select(Movement).where(
                        Movement.receivable_id == uuid.UUID(receivable_id),
                        Movement.movement_type == "REVERSAL",
                    )
                )
            ).all()
        )
    assert len(reversals) == 1


async def test_reverse_movement_requires_write_scope(client) -> None:
    receivable_id = await _create_receivable_via_event_http(
        key_prefix="api-rev3", sequential="000000952", total=Decimal("50.00")
    )
    write_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(write_token, "rev-api-pay-0003"),
        json={
            "cashAmount": "50.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    async with SessionFactory() as session:
        movement = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == uuid.UUID(receivable_id),
                Movement.movement_type == "PAYMENT",
            )
        )
        movement_id = movement.id

    read_only_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    response = await client.post(
        f"/api/v1/receivables/{receivable_id}/movements/{movement_id}/reversal",
        headers=auth(read_only_token, "rev-api-scope-0001"),
        json={"reason": "Sin permiso de escritura"},
    )
    assert response.status_code == 403


async def test_payment_then_reversal_cycle_restores_previous_balance(client) -> None:
    """Integracion: cobro -> reverso -> saldo vuelve exactamente al previo."""

    receivable_id = await _create_receivable_via_event_http(
        key_prefix="api-rev4", sequential="000000953", total=Decimal("90.00")
    )
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )

    before_response = await client.get(f"/api/v1/receivables/{receivable_id}", headers=auth(token))
    balance_before = before_response.json()["openAmount"]
    assert balance_before == "90.00"

    await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "rev-cycle-pay-0001"),
        json={
            "cashAmount": "33.00",
            "paymentDate": "2026-07-10",
            "retentions": [],
            "discounts": [],
        },
    )
    mid_response = await client.get(f"/api/v1/receivables/{receivable_id}", headers=auth(token))
    assert mid_response.json()["openAmount"] == "57.00"

    async with SessionFactory() as session:
        movement = await session.scalar(
            select(Movement).where(
                Movement.receivable_id == uuid.UUID(receivable_id),
                Movement.movement_type == "PAYMENT",
            )
        )
        movement_id = movement.id

    await client.post(
        f"/api/v1/receivables/{receivable_id}/movements/{movement_id}/reversal",
        headers=auth(token, "rev-cycle-0001-0001"),
        json={"reason": "Cliente reporto cobro duplicado"},
    )

    after_response = await client.get(f"/api/v1/receivables/{receivable_id}", headers=auth(token))
    assert after_response.json()["openAmount"] == balance_before

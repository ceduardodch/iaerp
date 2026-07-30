import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.platform import OutboxEvent
from app.models.receivables import CollectionPolicy, CollectionReminder
from app.workers.collections import (
    COLLECTION_REMINDER_DUE_EVENT,
    _render_collection_email,
    dispatch_due_reminders_once,
    handle_collection_reminder_due,
)
from app.workers.outbox import OutboxMessage

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


def test_collection_email_renders_tenant_template_and_payment_table() -> None:
    policy = CollectionPolicy(
        tenant_id=TENANT_A,
        email_subject="Cobro {{empresa}} - {{cliente}}",
        email_body="Saldo {{saldo}}; atraso {{dias_atraso}} días.",
        payment_instructions="Banco ejemplo\nCuenta 123456",
    )
    subject, plain, html = _render_collection_email(
        policy=policy,
        company_name="Empresa prueba",
        party_name="Cliente prueba",
        open_amount=Decimal("123.45"),
        due_date=date(2026, 7, 1),
        as_of=date(2026, 7, 5),
    )
    assert subject == "Cobro Empresa prueba - Cliente prueba"
    assert "Saldo $123.45; atraso 4 días." in plain
    assert "Banco ejemplo" in plain
    assert "Fecha de vencimiento" in html
    assert "Días de atraso" in html


async def test_due_reminder_is_queued_once_and_failure_is_visible() -> None:
    async with SessionFactory() as session, session.begin():
        party = Party(
            tenant_id=TENANT_A,
            name="Cliente cobranza",
            identification_type="CEDULA",
            identification_number="1713209771",
            email="collections@example.com",
            roles=["CUSTOMER"],
        )
        session.add(party)
        await session.flush()
        reminder = CollectionReminder(
            tenant_id=TENANT_A,
            party_id=party.id,
            channel="EMAIL",
            template_id="payment_reminder",
            recipient=party.email,
            status="PENDING",
            scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(reminder)
        await session.flush()
        reminder_id = reminder.id

    assert await dispatch_due_reminders_once() == 1
    assert await dispatch_due_reminders_once() == 0

    async with SessionFactory() as session:
        reminder = await session.get(CollectionReminder, reminder_id)
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == str(reminder_id))
        )
        assert reminder is not None
        assert reminder.status == "PROCESSING"
        assert reminder.attempts == 1
        assert event is not None
        message = OutboxMessage(
            event_id=event.id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            correlation_id=event.correlation_id,
            attempts=1,
        )

    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(session, message)

    async with SessionFactory() as session:
        reminder = await session.get(CollectionReminder, reminder_id)
        assert reminder is not None
        assert reminder.status == "FAILED"
        assert reminder.error_message == "Google Workspace is not connected"
        assert message.event_type == COLLECTION_REMINDER_DUE_EVENT

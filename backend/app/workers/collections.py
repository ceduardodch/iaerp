from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.platform import OutboxEvent
from app.models.receivables import (
    CollectionPolicy,
    CollectionReminder,
    Receivable,
    ReceivableInstallment,
)
from app.services import crm_integrations
from app.workers.outbox import OutboxMessage

FISCAL_TZ = ZoneInfo("America/Guayaquil")
COLLECTION_REMINDER_DUE_EVENT = "collection.reminder.due"
CONSUMER_NAME = "iaerp.collection-reminders"


async def schedule_receivable_reminders(
    session: AsyncSession,
    *,
    receivable: Receivable,
    installments: list[ReceivableInstallment],
) -> int:
    policy = await session.get(CollectionPolicy, receivable.tenant_id)
    if policy is None or not policy.enabled:
        return 0
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == receivable.tenant_id,
            Party.id == receivable.party_id,
        )
    )
    if party is None or party.consent_opt_out:
        return 0
    created = 0
    offsets = [int(value) for value in policy.offsets_days.split(",") if value]
    channels = [value for value in policy.channels.split(",") if value]
    for installment in installments:
        for offset in offsets:
            local_datetime = datetime.combine(
                installment.due_date + timedelta(days=offset),
                time(hour=policy.send_hour),
                tzinfo=FISCAL_TZ,
            )
            scheduled_at = local_datetime.astimezone(UTC)
            for channel in channels:
                recipient = party.email if channel == "EMAIL" else party.phone
                status = "PENDING" if recipient else "SKIPPED"
                session.add(
                    CollectionReminder(
                        tenant_id=receivable.tenant_id,
                        party_id=party.id,
                        receivable_id=receivable.id,
                        installment_id=installment.id,
                        channel=channel,
                        template_id=(
                            policy.email_template_id
                            if channel == "EMAIL"
                            else policy.whatsapp_template_id
                        ),
                        recipient=recipient or "missing-contact",
                        status=status,
                        scheduled_at=scheduled_at,
                        error_message=None if recipient else f"Party has no contact for {channel}",
                    )
                )
                created += 1
    await session.flush()
    return created


async def dispatch_due_reminders_once() -> int:
    async with SessionFactory() as session:
        now = datetime.now(UTC)
        reminders = list(
            await session.scalars(
                select(CollectionReminder)
                .where(
                    CollectionReminder.scheduled_at <= now,
                    or_(
                        CollectionReminder.status == "PENDING",
                        (
                            (CollectionReminder.status == "FAILED")
                            & (CollectionReminder.attempts < 3)
                        ),
                        (
                            (CollectionReminder.status == "PROCESSING")
                            & (CollectionReminder.updated_at < now - timedelta(minutes=10))
                        ),
                    ),
                )
                .order_by(CollectionReminder.scheduled_at)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for reminder in reminders:
            reminder.status = "PROCESSING"
            reminder.attempts += 1
            session.add(
                OutboxEvent(
                    tenant_id=reminder.tenant_id,
                    event_type=COLLECTION_REMINDER_DUE_EVENT,
                    aggregate_type="collection_reminder",
                    aggregate_id=str(reminder.id),
                    payload={"reminder_id": str(reminder.id)},
                    correlation_id=f"collection-reminder:{reminder.id}:{reminder.attempts}",
                    available_at=now,
                )
            )
        await session.commit()
        return len(reminders)


async def handle_collection_reminder_due(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    try:
        reminder_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    reminder = await session.scalar(
        select(CollectionReminder)
        .where(
            CollectionReminder.id == reminder_id,
            CollectionReminder.tenant_id == message.tenant_id,
        )
        .with_for_update()
    )
    if reminder is None or reminder.status == "SENT":
        return

    integration = await crm_integrations.google_integration_for_tenant(session, reminder.tenant_id)
    context = AuthContext(
        actor_id=str(integration.user_id) if integration else str(uuid.UUID(int=0)),
        actor_type="SYSTEM",
        tenant_id=reminder.tenant_id,
        roles=frozenset({"scheduler"}),
        scopes=frozenset({"communications:write"}),
        token_id="collection-scheduler",
    )
    try:
        if reminder.channel == "EMAIL":
            await crm_integrations.send_google_email(
                session,
                context,
                recipient=reminder.recipient,
                subject="Recordatorio de pago",
                message=(
                    "Le recordamos que mantiene un saldo pendiente. "
                    "Si ya realizó el pago, por favor ignore este mensaje."
                ),
            )
        else:
            await crm_integrations.send_whatsapp_message(
                session,
                context,
                recipient=reminder.recipient,
                message="Recordatorio de pago pendiente",
                template_id=reminder.template_id,
            )
    except Exception as exc:
        detail = getattr(exc, "detail", str(exc))
        reminder.status = "FAILED"
        reminder.error_message = str(detail)[:1000]
    else:
        reminder.status = "SENT"
        reminder.sent_at = datetime.now(UTC)
        reminder.error_message = None


async def run_collection_scheduler() -> None:
    while True:
        await dispatch_due_reminders_once()
        await asyncio.sleep(60)

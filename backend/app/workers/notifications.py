"""Despacho de avisos internos, sobre el outbox que ya existe.

Mismo patron probado de ``workers/collections.py``: el bucle marca los eventos
vencidos como ``PROCESSING`` bajo ``FOR UPDATE SKIP LOCKED`` y emite un
``OutboxEvent``; el envio real ocurre en el handler, con los reintentos y el
dead-letter que el outbox ya sabe hacer. No se inventa un mecanismo de
reintentos propio.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionFactory
from app.integrations.notifications.email_sender import EmailSender
from app.models.notifications import NotificationEvent
from app.models.platform import OutboxEvent
from app.services.notifications import channels, delivery, planner
from app.workers.outbox import OutboxMessage

NOTIFICATION_DUE_EVENT = "notification.due"
CONSUMER_NAME = "iaerp.notifications"

_BATCH_SIZE = 25
_STUCK_AFTER = timedelta(minutes=10)
_MAX_ATTEMPTS = 3


def get_email_sender() -> EmailSender:
    """Proveedor activo: Brevo si hay clave de plataforma, si no el stub.

    Sigue siendo una funcion y no una constante para que las pruebas la puedan
    sustituir y para que el cambio de proveedor se note en la siguiente entrega
    sin reiniciar nada.
    """
    return channels.build_email_sender()


async def dispatch_due_notifications_once() -> int:
    """Encola los avisos cuya hora ya llego. Devuelve cuantos tomo."""
    async with SessionFactory() as session:
        now = datetime.now(UTC)
        events = list(
            await session.scalars(
                select(NotificationEvent)
                .where(
                    NotificationEvent.scheduled_at <= now,
                    or_(
                        NotificationEvent.status == "PENDING",
                        (
                            (NotificationEvent.status == "FAILED")
                            & (NotificationEvent.attempts < _MAX_ATTEMPTS)
                        ),
                        (
                            (NotificationEvent.status == "PROCESSING")
                            & (NotificationEvent.updated_at < now - _STUCK_AFTER)
                        ),
                    ),
                )
                .order_by(NotificationEvent.scheduled_at)
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.status = "PROCESSING"
            event.attempts += 1
            session.add(
                OutboxEvent(
                    tenant_id=event.tenant_id,
                    event_type=NOTIFICATION_DUE_EVENT,
                    aggregate_type="notification_event",
                    aggregate_id=str(event.id),
                    payload={"notification_event_id": str(event.id)},
                    correlation_id=f"notification:{event.id}:{event.attempts}",
                    available_at=now,
                )
            )
        await session.commit()
        return len(events)


async def handle_notification_due(session: AsyncSession, message: OutboxMessage) -> None:
    try:
        event_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    event = await session.scalar(
        select(NotificationEvent)
        .where(
            NotificationEvent.id == event_id,
            NotificationEvent.tenant_id == message.tenant_id,
        )
        .with_for_update()
    )
    # Un evento ya resuelto no se reenvia aunque el outbox reintente: la
    # entrega es lo unico que no se puede deshacer.
    if event is None or event.status in {"SENT", "STUBBED", "SKIPPED", "CANCELLED"}:
        return
    await delivery.deliver_event(session, event=event, sender=get_email_sender())


async def run_notification_scheduler() -> None:
    while True:
        await planner.plan_notifications_once()
        await dispatch_due_notifications_once()
        await asyncio.sleep(60)


__all__ = [
    "CONSUMER_NAME",
    "NOTIFICATION_DUE_EVENT",
    "dispatch_due_notifications_once",
    "get_email_sender",
    "handle_notification_due",
    "run_notification_scheduler",
]

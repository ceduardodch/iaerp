import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.platform import DeadLetter, InboxEvent, OutboxEvent

settings = get_settings()


@dataclass(frozen=True)
class OutboxMessage:
    event_id: uuid.UUID
    tenant_id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, object]
    correlation_id: str
    attempts: int


class EventPublisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None: ...


def _redact_error(exc: BaseException) -> str:
    value = f"{type(exc).__name__}: {exc}"
    value = re.sub(
        r"(?i)\b(password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        value,
    )
    return value[:1000]


def retry_delay(attempts: int) -> timedelta:
    """Backoff exponencial (base 2, tope 300s) segun el numero de intentos.

    Publica (sin guion bajo) porque ``workers/sri_transmission.py`` la
    reutiliza para reprogramar su propio ``OutboxEvent`` ante un fallo tecnico
    (TIMEOUT del simulador/SRI), en vez de duplicar la formula de backoff.
    """

    return timedelta(seconds=min(2 ** max(attempts - 1, 0), 300))


# Alias retrocompatible: el resto de este modulo ya usaba el nombre privado.
_retry_delay = retry_delay


async def claim_outbox_batch(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> list[OutboxMessage]:
    claimed_at = now or datetime.now(UTC)
    limit = batch_size or settings.OUTBOX_BATCH_SIZE
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.dead_lettered_at.is_(None),
            OutboxEvent.available_at <= claimed_at,
            or_(
                OutboxEvent.lease_until.is_(None),
                OutboxEvent.lease_until < claimed_at,
            ),
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    entities = list((await session.scalars(statement)).all())
    lease_until = claimed_at + timedelta(seconds=settings.OUTBOX_LEASE_SECONDS)
    messages: list[OutboxMessage] = []
    for entity in entities:
        entity.lease_until = lease_until
        entity.attempts += 1
        messages.append(
            OutboxMessage(
                event_id=entity.id,
                tenant_id=entity.tenant_id,
                event_type=entity.event_type,
                aggregate_type=entity.aggregate_type,
                aggregate_id=entity.aggregate_id,
                payload=entity.payload,
                correlation_id=entity.correlation_id,
                attempts=entity.attempts,
            )
        )
    await session.flush()
    return messages


async def _mark_published(message: OutboxMessage) -> None:
    async with SessionFactory() as session, session.begin():
        entity = await session.get(OutboxEvent, message.event_id, with_for_update=True)
        if entity is None or entity.published_at is not None:
            return
        entity.published_at = datetime.now(UTC)
        entity.lease_until = None
        entity.last_error = None


async def _mark_failed(message: OutboxMessage, exc: BaseException) -> None:
    now = datetime.now(UTC)
    error = _redact_error(exc)
    async with SessionFactory() as session, session.begin():
        entity = await session.get(OutboxEvent, message.event_id, with_for_update=True)
        if entity is None or entity.published_at is not None:
            return
        entity.lease_until = None
        entity.last_error = error
        if entity.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
            entity.dead_lettered_at = now
            session.add(
                DeadLetter(
                    tenant_id=entity.tenant_id,
                    source_type="OUTBOX",
                    source_id=entity.id,
                    event_type=entity.event_type,
                    payload={
                        "aggregate_type": entity.aggregate_type,
                        "aggregate_id": entity.aggregate_id,
                        "correlation_id": entity.correlation_id,
                    },
                    error=error,
                    attempts=entity.attempts,
                )
            )
        else:
            entity.available_at = now + _retry_delay(entity.attempts)


async def dispatch_outbox_once(publisher: EventPublisher) -> int:
    async with SessionFactory() as session, session.begin():
        messages = await claim_outbox_batch(session)

    for message in messages:
        try:
            await publisher.publish(message)
        except BaseException as exc:
            await _mark_failed(message, exc)
        else:
            await _mark_published(message)
    return len(messages)


InboxHandler = Callable[[AsyncSession, OutboxMessage], Awaitable[None]]


async def consume_once(
    *,
    consumer_name: str,
    message: OutboxMessage,
    handler: InboxHandler,
) -> bool:
    async with SessionFactory() as session:
        try:
            async with session.begin():
                existing = await session.scalar(
                    select(InboxEvent)
                    .where(
                        InboxEvent.consumer_name == consumer_name,
                        InboxEvent.event_id == message.event_id,
                    )
                    .with_for_update()
                )
                if existing is not None and existing.status == "COMPLETED":
                    return False
                inbox = InboxEvent(
                    tenant_id=message.tenant_id,
                    consumer_name=consumer_name,
                    event_id=message.event_id,
                )
                session.add(inbox)
                await session.flush()
                await handler(session, message)
                inbox.status = "COMPLETED"
                inbox.processed_at = datetime.now(UTC)
            return True
        except IntegrityError:
            return False


async def run_dispatcher(
    publisher: EventPublisher,
    *,
    poll_seconds: float = 1.0,
) -> None:
    while True:
        processed = await dispatch_outbox_once(publisher)
        if processed == 0:
            await asyncio.sleep(poll_seconds)


def messages_for_tenant(
    messages: Sequence[OutboxMessage],
    tenant_id: uuid.UUID,
) -> list[OutboxMessage]:
    return [message for message in messages if message.tenant_id == tenant_id]

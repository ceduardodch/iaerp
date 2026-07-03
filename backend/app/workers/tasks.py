import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.workers.celery_app import celery_app
from app.workers.outbox import OutboxMessage, consume_once


async def _acknowledge_event(
    _session: AsyncSession,
    _message: OutboxMessage,
) -> None:
    return None


@celery_app.task(name="iaerp.consume_event")  # type: ignore[untyped-decorator]
def consume_event(
    *,
    event_id: str,
    tenant_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, object],
    correlation_id: str,
    attempts: int,
) -> bool:
    message = OutboxMessage(
        event_id=uuid.UUID(event_id),
        tenant_id=uuid.UUID(tenant_id),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        correlation_id=correlation_id,
        attempts=attempts,
    )
    return asyncio.run(
        consume_once(
            consumer_name="iaerp.default",
            message=message,
            handler=_acknowledge_event,
        )
    )

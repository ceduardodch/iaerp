import asyncio
import uuid
from collections.abc import Coroutine

from celery.signals import worker_process_shutdown
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.workers.celery_app import celery_app
from app.workers.outbox import OutboxMessage, consume_once

# Un event loop por proceso del worker: asyncio.run crearia un loop nuevo por
# task y las conexiones del pool asyncpg quedarian atadas a un loop cerrado
# ("attached to a different loop" intermitente en prefork).
_loop: asyncio.AbstractEventLoop | None = None


def _run[T](coroutine: Coroutine[object, object, T]) -> T:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coroutine)


@worker_process_shutdown.connect  # type: ignore[untyped-decorator]
def _dispose_engine_and_loop(**_kwargs: object) -> None:
    global _loop
    if _loop is not None and not _loop.is_closed():
        _loop.run_until_complete(engine.dispose())
        _loop.close()
    _loop = None


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
    return _run(
        consume_once(
            consumer_name="iaerp.default",
            message=message,
            handler=_acknowledge_event,
        )
    )

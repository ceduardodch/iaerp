import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine

from celery.signals import worker_process_shutdown
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine
from app.workers.celery_app import celery_app
from app.workers.outbox import OutboxMessage, consume_once
from app.workers.receivables import CONSUMER_NAME as RECEIVABLES_CONSUMER
from app.workers.receivables import handle_credit_note_authorized, handle_invoice_authorized
from app.workers.sri_transmission import CONSUMER_NAME as SRI_TRANSMISSION_CONSUMER
from app.workers.sri_transmission import CREDIT_NOTE_AUTHORIZED_EVENT, handle_invoice_signed

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


Handler = Callable[[AsyncSession, OutboxMessage], Awaitable[None]]

# Ruteo por event_type: cada entrada declara el consumer_name (para el
# aislamiento at-least-once de InboxEvent, ver workers/outbox.consume_once) y
# el handler a invocar. Eventos sin entrada aqui caen al no-op historico
# (_acknowledge_event bajo "iaerp.default"), preservando compatibilidad con
# los eventos ya emitidos por otros modulos (parties.created, etc.) que no
# tienen un consumidor dedicado todavia.
_HANDLERS_BY_EVENT_TYPE: dict[str, tuple[str, Handler]] = {
    "invoice.signed": (SRI_TRANSMISSION_CONSUMER, handle_invoice_signed),
    "invoice.authorized": (RECEIVABLES_CONSUMER, handle_invoice_authorized),
    CREDIT_NOTE_AUTHORIZED_EVENT: (RECEIVABLES_CONSUMER, handle_credit_note_authorized),
}

_DEFAULT_CONSUMER_NAME = "iaerp.default"


def _resolve_consumer(event_type: str) -> tuple[str, Handler]:
    return _HANDLERS_BY_EVENT_TYPE.get(event_type, (_DEFAULT_CONSUMER_NAME, _acknowledge_event))


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
    consumer_name, handler = _resolve_consumer(event_type)
    return _run(
        consume_once(
            consumer_name=consumer_name,
            message=message,
            handler=handler,
        )
    )

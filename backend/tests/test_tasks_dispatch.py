"""Pruebas de ruteo por ``event_type`` en ``workers/tasks.py``.

``consume_event`` (la task Celery) debe invocar el handler dedicado de
``invoice.signed`` y mantener el comportamiento no-op historico
(``_acknowledge_event``) para cualquier otro tipo de evento, sin romper los
consumidores existentes (parties.created, etc.) que todavia no tienen un
handler dedicado.
"""

import uuid

from app.workers import sri_transmission, tasks
from app.workers.outbox import OutboxMessage


def _message(event_type: str) -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_type=event_type,
        aggregate_type="sales_document",
        aggregate_id=str(uuid.uuid4()),
        payload={},
        correlation_id=str(uuid.uuid4()),
        attempts=1,
    )


def test_resolve_consumer_routes_invoice_signed_to_sri_transmission_handler() -> None:
    consumer_name, handler = tasks._resolve_consumer("invoice.signed")
    assert consumer_name == sri_transmission.CONSUMER_NAME
    assert handler is sri_transmission.handle_invoice_signed


def test_resolve_consumer_falls_back_to_default_for_unknown_event_types() -> None:
    consumer_name, handler = tasks._resolve_consumer("party.created")
    assert consumer_name == "iaerp.default"
    assert handler is tasks._acknowledge_event


async def test_default_handler_is_a_true_no_op() -> None:
    # Guards against regressing the historical no-op behaviour for event
    # types that do not have a dedicated consumer yet.
    result = await tasks._acknowledge_event(None, _message("party.created"))  # type: ignore[arg-type]
    assert result is None


def test_consume_event_task_dispatches_to_resolved_handler(monkeypatch) -> None:
    """``consume_event`` (la task Celery) debe usar ``_resolve_consumer``.

    Se reemplaza ``_run`` por una ejecucion sincrona real de la corrutina
    (en vez de un stub que la descarta sin awaitear) para no dejar un
    warning de "coroutine never awaited" y para verificar de punta a punta
    que el resultado de ``consume_once`` se propaga.
    """

    import asyncio

    captured: dict[str, object] = {}

    async def fake_consume_once(*, consumer_name, message, handler):
        captured["consumer_name"] = consumer_name
        captured["handler"] = handler
        return True

    monkeypatch.setattr(tasks, "consume_once", fake_consume_once)
    monkeypatch.setattr(tasks, "_run", asyncio.run)

    message = _message("invoice.signed")
    result = tasks.consume_event(
        event_id=str(message.event_id),
        tenant_id=str(message.tenant_id),
        event_type=message.event_type,
        aggregate_type=message.aggregate_type,
        aggregate_id=message.aggregate_id,
        payload=message.payload,
        correlation_id=message.correlation_id,
        attempts=message.attempts,
    )
    assert result is True
    assert captured["consumer_name"] == sri_transmission.CONSUMER_NAME
    assert captured["handler"] is sri_transmission.handle_invoice_signed

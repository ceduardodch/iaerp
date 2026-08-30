"""HTTP de ``GET /ops/failures``: scopes, aislamiento por tenant y filtros.

Este endpoint es la primera pieza de observabilidad operativa: hasta ahora un
fallo terminal quedaba en ``dead_letters`` y solo se podia ver con SQL manual.

La prueba mas importante es
``test_dead_lettered_outbox_event_appears_once``: ``dead_letters`` es la fuente
canonica y completa, porque el dispatcher (``workers/outbox.py::_mark_failed``)
marca ``dead_lettered_at`` en el ``OutboxEvent`` *y ademas* inserta la fila de
``DeadLetter``. Unir ambas tablas duplicaria todos los fallos del dispatcher.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.platform import DeadLetter, OutboxEvent
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


async def _add_dead_letter(
    *,
    tenant_id: uuid.UUID,
    event_type: str = "invoice.signed",
    error: str = "SRI timeout",
    status: str = "OPEN",
    source_id: uuid.UUID | None = None,
    correlation_id: str = "corr-0001",
    created_at: datetime = NOW,
) -> uuid.UUID:
    entity = DeadLetter(
        tenant_id=tenant_id,
        source_type="OUTBOX",
        source_id=source_id or uuid.uuid4(),
        event_type=event_type,
        payload={
            "aggregate_type": "sales_document",
            "aggregate_id": "doc-1",
            "correlation_id": correlation_id,
        },
        error=error,
        attempts=5,
        status=status,
        created_at=created_at,
    )
    async with SessionFactory() as session, session.begin():
        session.add(entity)
        await session.flush()
        return entity.id


async def test_list_failures_requires_operations_read_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))
    assert response.status_code == 403, response.text


async def test_list_failures_returns_dead_letters(client) -> None:
    failure_id = await _add_dead_letter(tenant_id=TENANT_A)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == str(failure_id)
    assert item["eventType"] == "invoice.signed"
    assert item["error"] == "SRI timeout"
    assert item["attempts"] == 5
    assert item["status"] == "OPEN"
    assert item["sourceType"] == "OUTBOX"
    # El correlation ID vive dentro del payload que escriben los workers; sin
    # extraerlo no hay forma de cruzar el fallo con los logs de la request.
    assert item["correlationId"] == "corr-0001"
    # "invoice.signed" es el unico event_type en la lista blanca de
    # classify_failure(): el panel de Incidencias del frontend usa este campo
    # para decidir si ofrece el boton de reintento, sin duplicar la lista
    # blanca en TypeScript.
    assert item["classification"] == "AUTO_RETRY"


async def test_list_failures_exposes_needs_human_for_unknown_event_types(client) -> None:
    """Cualquier event_type fuera de la lista blanca es NEEDS_HUMAN (default deny)."""
    await _add_dead_letter(
        tenant_id=TENANT_A, event_type="collection.reminder.due", correlation_id="corr-needs-human"
    )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.json()[0]["classification"] == "NEEDS_HUMAN"


async def test_list_failures_is_tenant_scoped(client) -> None:
    await _add_dead_letter(tenant_id=TENANT_B, correlation_id="corr-otro-tenant")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_list_failures_filters_by_status(client) -> None:
    await _add_dead_letter(tenant_id=TENANT_A, status="OPEN", correlation_id="abierta")
    await _add_dead_letter(tenant_id=TENANT_A, status="RESOLVED", correlation_id="resuelta")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures?status=OPEN", headers=auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["correlationId"] for item in body] == ["abierta"]


async def test_list_failures_orders_newest_first(client) -> None:
    await _add_dead_letter(
        tenant_id=TENANT_A, correlation_id="vieja", created_at=NOW - timedelta(hours=2)
    )
    await _add_dead_letter(tenant_id=TENANT_A, correlation_id="nueva", created_at=NOW)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))

    assert response.status_code == 200, response.text
    assert [item["correlationId"] for item in response.json()] == ["nueva", "vieja"]


async def test_dead_lettered_outbox_event_appears_once(client) -> None:
    """El camino del dispatcher escribe en las DOS tablas: no duplicar.

    ``workers/outbox.py::_mark_failed`` marca ``dead_lettered_at`` en el
    ``OutboxEvent`` y ademas inserta el ``DeadLetter``. Si este endpoint uniera
    ambas tablas, cada fallo del dispatcher se veria dos veces en la bandeja.
    """
    event_id = uuid.uuid4()
    async with SessionFactory() as session, session.begin():
        session.add(
            OutboxEvent(
                id=event_id,
                tenant_id=TENANT_A,
                event_type="invoice.signed",
                aggregate_type="sales_document",
                aggregate_id="doc-1",
                payload={},
                correlation_id="corr-dispatcher",
                attempts=5,
                available_at=NOW,
                dead_lettered_at=NOW,
                last_error="SRI timeout",
            )
        )
    await _add_dead_letter(
        tenant_id=TENANT_A, source_id=event_id, correlation_id="corr-dispatcher"
    )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures", headers=auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1, f"el fallo del dispatcher se duplico: {body}"
    assert body[0]["sourceId"] == str(event_id)


async def test_list_failures_respects_limit(client) -> None:
    for index in range(3):
        await _add_dead_letter(
            tenant_id=TENANT_A,
            correlation_id=f"corr-{index}",
            created_at=NOW - timedelta(minutes=index),
        )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.get("/api/v1/ops/failures?limit=2", headers=auth(token))

    assert response.status_code == 200, response.text
    assert [item["correlationId"] for item in response.json()] == ["corr-0", "corr-1"]


# --- POST /ops/failures/{id}/retry -----------------------------------------
#
# Reintento MANUAL disparado por un humano con el scope nuevo
# ``operations:write``. A diferencia del futuro agente de la Fase 3
# (pendiente 11, gateado por ``classify_failure() == AUTO_RETRY``), aquí un
# humano ya ejerció su propio juicio al presionar el botón: el endpoint no
# repite ese gate, solo exige que el fallo siga ``OPEN`` y pertenezca al
# tenant. Encola un ``OutboxEvent`` FRESCO (id nuevo) en vez de reabrir el
# original, siguiendo el mismo patrón ya probado en
# ``workers/sri_transmission.py::_enqueue_followup``: reabrir el evento
# original no sirve porque su ``InboxEvent`` puede seguir ``COMPLETED`` y
# ``consume_once`` lo deduplicaría.


async def test_retry_failure_requires_operations_write_scope(client) -> None:
    failure_id = await _add_dead_letter(tenant_id=TENANT_A)

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-scope-0001-key"),
    )
    assert response.status_code == 403, response.text


async def test_retry_failure_reopens_and_enqueues_fresh_outbox_event(client) -> None:
    failure_id = await _add_dead_letter(
        tenant_id=TENANT_A, event_type="invoice.signed", correlation_id="corr-retry"
    )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:write"])
    response = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-ok-0001-key"),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(failure_id)
    assert body["status"] == "RESOLVED"
    assert body["resolvedAt"] is not None

    async with SessionFactory() as session:
        resolved = await session.get(DeadLetter, failure_id)
        assert resolved is not None
        assert resolved.status == "RESOLVED"

        fresh_events = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.tenant_id == TENANT_A,
                        OutboxEvent.event_type == "invoice.signed",
                        OutboxEvent.aggregate_id == "doc-1",
                    )
                )
            ).all()
        )
        assert len(fresh_events) == 1, "debe crear un OutboxEvent fresco para redisparar el handler"
        fresh = fresh_events[0]
        assert fresh.id != failure_id
        assert fresh.attempts == 0
        assert fresh.published_at is None
        assert fresh.dead_lettered_at is None
        assert fresh.correlation_id == "corr-retry"


async def test_retry_failure_twice_returns_409(client) -> None:
    failure_id = await _add_dead_letter(tenant_id=TENANT_A, correlation_id="corr-doble")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:write"])
    first = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-doble-0001-key"),
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-doble-0002-key"),
    )
    assert second.status_code == 409, second.text


async def test_retry_failure_missing_id_returns_404(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:write"])
    response = await client.post(
        f"/api/v1/ops/failures/{uuid.uuid4()}/retry",
        headers=auth(token, "retry-missing-0001-key"),
    )
    assert response.status_code == 404, response.text


async def test_retry_failure_is_tenant_scoped(client) -> None:
    failure_id = await _add_dead_letter(tenant_id=TENANT_B, correlation_id="corr-otro-tenant")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:write"])
    response = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-tenant-0001-key"),
    )
    assert response.status_code == 404, response.text


async def test_retry_failure_idempotency_key_replay_does_not_duplicate_outbox_event(
    client,
) -> None:
    failure_id = await _add_dead_letter(tenant_id=TENANT_A, correlation_id="corr-idem")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:write"])
    first = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-idem-0001-key"),
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/ops/failures/{failure_id}/retry",
        headers=auth(token, "retry-idem-0001-key"),
    )
    assert second.status_code == 200, second.text
    assert first.json() == second.json()

    async with SessionFactory() as session:
        fresh_events = list(
            (
                await session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.tenant_id == TENANT_A,
                        OutboxEvent.aggregate_id == "doc-1",
                        OutboxEvent.event_type == "invoice.signed",
                    )
                )
            ).all()
        )
        assert len(fresh_events) == 1

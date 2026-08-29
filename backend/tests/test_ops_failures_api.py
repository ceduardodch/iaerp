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

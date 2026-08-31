"""Fase 3 (pendiente 10, `docs/OBSERVABILIDAD_PENDIENTES.md`): `ops.list_failures`.

Tool MCP de solo lectura que reutiliza `services/ops_failures.py::list_failures`
sin duplicar la consulta -- el mismo caso de uso que `GET /ops/failures` (REST).
Devuelve `classification` para que el agente sepa que puede tocar con el futuro
`ops.retry_failure` (pendiente 11) y que debe escalar a un humano.

Cubre, con el mismo patron que `test_mcp_receivables.py`:

- Catalogo filtrado por scope: sin `operations:read` la tool no aparece.
- Aislamiento por tenant: solo ve los `dead_letters` del tenant del token.
- Equivalencia con REST: el mismo fallo se ve igual por ambas superficies,
  incluida la `classification` calculada por `classify_failure()`.
- Filtro por `status` y limite, igual que el endpoint REST.
- Solo lectura: nunca bloqueada por el kill switch de automatizacion
  (`AutomationSettings.writes_enabled` en `False` por defecto).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.routing import Mount

from app.db.session import SessionFactory
from app.main import app
from app.mcp.server import mcp
from app.models.platform import DeadLetter
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _replace_mcp_mount(fresh_mcp_app) -> None:
    """Ver `test_mcp_invoices.py::_replace_mcp_mount` para el detalle completo."""
    routes = app.router.routes
    for index, route in enumerate(routes):
        if isinstance(route, Mount) and route.path == "":
            routes[index] = Mount("/", app=fresh_mcp_app)
            return
    raise AssertionError("MCP mount not found on app.router.routes")


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    """Ver `test_mcp_invoices.py::mcp_lifespan`: session manager fresco por test."""
    mcp._session_manager = None
    fresh_mcp_app = mcp.streamable_http_app()
    _replace_mcp_mount(fresh_mcp_app)
    async with app.router.lifespan_context(app):
        yield


@asynccontextmanager
async def mcp_session(token: str) -> AsyncIterator[ClientSession]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {token}"},
    ) as http_client:
        async with streamable_http_client(
            "http://localhost:8000/mcp",
            http_client=http_client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def _add_dead_letter(
    *,
    tenant_id: uuid.UUID,
    event_type: str = "invoice.signed",
    error: str = "SRI timeout",
    status: str = "OPEN",
    correlation_id: str = "corr-0001",
    created_at: datetime = NOW,
) -> uuid.UUID:
    entity = DeadLetter(
        tenant_id=tenant_id,
        source_type="OUTBOX",
        source_id=uuid.uuid4(),
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


async def test_mcp_ops_list_failures_catalog_filtered_by_scope(client) -> None:
    """Sin `operations:read` la tool no aparece; con el scope, si."""
    no_scope_token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    full_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["context:read", "operations:read"]
    )

    async with mcp_lifespan():
        async with mcp_session(no_scope_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "ops.list_failures" not in names

        async with mcp_session(full_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "ops.list_failures" in names


async def test_mcp_ops_list_failures_is_tenant_scoped(client) -> None:
    failure_a = await _add_dead_letter(tenant_id=TENANT_A, correlation_id="corr-a")
    await _add_dead_letter(tenant_id=TENANT_B, correlation_id="corr-b")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("ops.list_failures", {})
        assert result.isError is False
        ids = {item["id"] for item in result.structuredContent["result"]}
        assert str(failure_a) in ids
        assert len(ids) == 1


async def test_mcp_ops_list_failures_equivalence_with_rest_including_classification(
    client,
) -> None:
    """El mismo fallo se ve igual por MCP y por REST, incluida la clasificacion."""
    failure_id = await _add_dead_letter(
        tenant_id=TENANT_A, event_type="invoice.signed", correlation_id="corr-equiv"
    )

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])

    rest_response = await client.get("/api/v1/ops/failures", headers=auth(token))
    assert rest_response.status_code == 200, rest_response.text
    rest_item = rest_response.json()[0]

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("ops.list_failures", {})
        assert result.isError is False
        mcp_item = result.structuredContent["result"][0]

    assert mcp_item["id"] == str(failure_id) == rest_item["id"]
    assert mcp_item["classification"] == "AUTO_RETRY" == rest_item["classification"]
    assert mcp_item["correlationId"] == "corr-equiv" == rest_item["correlationId"]


async def test_mcp_ops_list_failures_filters_by_status(client) -> None:
    await _add_dead_letter(tenant_id=TENANT_A, status="OPEN", correlation_id="abierta")
    await _add_dead_letter(tenant_id=TENANT_A, status="RESOLVED", correlation_id="resuelta")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("ops.list_failures", {"status": "OPEN"})
        assert result.isError is False
        correlation_ids = [item["correlationId"] for item in result.structuredContent["result"]]
        assert correlation_ids == ["abierta"]


async def test_mcp_ops_list_failures_not_blocked_by_automation_kill_switch(client) -> None:
    """Solo lectura: nunca pasa por `_require_automation_writes`."""
    await _add_dead_letter(tenant_id=TENANT_A, correlation_id="corr-kill")

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["operations:read"])

    # AutomationSettings.writes_enabled defaults to False (ver conftest).
    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("ops.list_failures", {})
        assert result.isError is False
        assert len(result.structuredContent["result"]) == 1


async def test_mcp_ops_list_failures_missing_scope_error_names_it(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("ops.list_failures", {})
        assert result.isError is True
        assert "missing scope operations:read" in result.content[0].text

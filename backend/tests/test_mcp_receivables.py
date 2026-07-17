"""E7-04: operar cartera/pagos por MCP (`receivables.*`).

Cubre, segun `docs/backlog/product-backlog.md` E7-04 ("Sin saldo negativo ni
bypass de permisos") y el mismo patron de `test_mcp_invoices.py` (E7-03):

- Catalogo filtrado por scope: un token sin `receivables:read`/`write`/`notify`
  no ve `receivables.list`/`record_payment`/`send_reminder`; con ellos, si.
- Aislamiento por tenant: `receivables.list` solo devuelve cartera del tenant
  del token, nunca la de otro tenant aunque exista con el mismo nombre de
  filtro/estado.
- Equivalencia REST/MCP: un cobro registrado por MCP se refleja igual por
  REST (`GET /receivables/{id}`) y viceversa (un cobro por REST se refleja
  igual por MCP), porque ambas superficies invocan exactamente el mismo caso
  de uso (`services/receivables.py::record_payment`).
- Sin saldo negativo / sin sobreaplicar: `record_payment` por MCP que excede
  el saldo abierto falla con `ToolError` y no crea ningun `Movement` (la
  transaccion de `execute_idempotent` se revierte completa ante la
  `HTTPException` 422 de `services/receivables.py::record_payment`).
- Kill switch: bloquea `record_payment`/`send_reminder` (escrituras/efecto
  externo), pero nunca `receivables.list` (solo lectura).
- Idempotencia: repetir `idempotencyKey` en `record_payment` no duplica el
  `Movement` de tipo `PAYMENT`.
- Seguridad negativa: scope faltante -> error con el scope exacto;
  receivable de otro tenant -> not found (nunca se filtra su existencia,
  incluso con automation writes habilitadas para descartar que el kill
  switch estuviera enmascarando el aislamiento de tenant).

Nota de transporte: igual que `test_mcp_invoices.py`, `mcp.session_manager`
solo admite un `.run()` por instancia y ese `.run()` ocurre dentro del
lifespan del `app`; cada test entra a `mcp_lifespan()` una sola vez.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import func, select
from starlette.routing import Mount

from app.db.session import SessionFactory
from app.main import app
from app.mcp.server import mcp
from app.models.receivables import CollectionReminder, Movement, Receivable
from app.workers.receivables import handle_invoice_authorized
from tests.test_billing_api import TENANT_A, TENANT_B, _setup_billing_masters, auth, token_for
from tests.test_receivables_flow import _insert_authorized_invoice, _message_for


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


async def _enable_automation_writes(client, token: str, key: str) -> None:
    response = await client.put(
        "/api/v1/automation/settings",
        headers=auth(token, key),
        json={"writesEnabled": True, "dailyAmountLimit": "1000.00"},
    )
    assert response.status_code == 200, response.text


async def _create_receivable(
    client,
    *,
    tenant_id: uuid.UUID,
    email: str,
    key_prefix: str,
    sequential: str,
    total: Decimal,
    issue_date: date = date(2026, 12, 1),
) -> tuple[str, dict[str, str]]:
    """Crea masters + factura AUTHORIZED de fixture + Receivable via el handler real.

    Mismo patron que `test_receivables_payments_api.py::_create_receivable_via_event`,
    parametrizado en tenant/email para poder crear cartera en dos tenants
    distintos dentro del mismo test (aislamiento).
    """
    setup_token = await token_for(
        client,
        email,
        tenant_id,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup_token, key_prefix=key_prefix)
    document = await _insert_authorized_invoice(
        tenant_id=tenant_id,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential=sequential,
        total=total,
        issue_date=issue_date,
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(document))
        await session.commit()
    async with SessionFactory() as session:
        receivable = await session.scalar(
            select(Receivable).where(Receivable.sales_document_id == document.id)
        )
    return str(receivable.id), masters


def _payment_payload(cash_amount: str, **overrides) -> dict:
    payload = {
        "cashAmount": cash_amount,
        "paymentDate": "2026-07-10",
        "retentions": [],
        "discounts": [],
    }
    payload.update(overrides)
    return payload


async def test_mcp_receivables_catalog_filtered_by_scope(client) -> None:
    """Sin scopes de cartera no aparecen; con ellos, las tres aparecen."""

    no_scope_token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    full_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["context:read", "receivables:read", "receivables:write", "receivables:notify"],
    )

    async with mcp_lifespan():
        async with mcp_session(no_scope_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "receivables.list" not in names
            assert "receivables.record_payment" not in names
            assert "receivables.send_reminder" not in names

        async with mcp_session(full_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "receivables.list",
                "receivables.record_payment",
                "receivables.send_reminder",
            }.issubset(names)


async def test_mcp_receivables_list_is_tenant_scoped(client) -> None:
    """`receivables.list` con el token de un tenant nunca devuelve cartera de otro."""

    receivable_a, _masters_a = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-iso-a",
        sequential="000000960",
        total=Decimal("70.00"),
    )
    receivable_b, _masters_b = await _create_receivable(
        client,
        tenant_id=TENANT_B,
        email="b@iaerp.local",
        key_prefix="mcp-rcv-iso-b",
        sequential="000000961",
        total=Decimal("90.00"),
    )

    token_a = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])

    async with mcp_lifespan(), mcp_session(token_a) as session:
        result = await session.call_tool("receivables.list", {})
        assert result.isError is False
        ids = {item["id"] for item in result.structuredContent["result"]}
        assert receivable_a in ids
        assert receivable_b not in ids


async def test_mcp_record_payment_equivalence_with_rest_same_balance_both_ways(client) -> None:
    """Un cobro por MCP se lee igual por REST, y uno por REST se lee igual por MCP."""

    receivable_id, _masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-equiv",
        sequential="000000962",
        total=Decimal("100.00"),
    )
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:write", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-rcv-equiv-enable-0001")

    async with mcp_lifespan():
        # 1) Cobro por MCP, leido por REST.
        async with mcp_session(token) as session:
            paid = await session.call_tool(
                "receivables.record_payment",
                {
                    "receivableId": receivable_id,
                    "payment": _payment_payload("40.00"),
                    "idempotencyKey": "mcp-rcv-equiv-pay-0001",
                },
            )
            assert paid.isError is False, paid.content
            mcp_item = paid.structuredContent

        assert mcp_item["openAmount"] == "60.00"
        assert mcp_item["status"] == "PARTIAL"

        rest_get = await client.get(f"/api/v1/receivables/{receivable_id}", headers=auth(token))
        assert rest_get.status_code == 200
        rest_item = rest_get.json()
        assert rest_item["openAmount"] == "60.00"
        assert rest_item["status"] == mcp_item["status"]

        # 2) Cobro por REST, leido por MCP.
        rest_pay = await client.post(
            f"/api/v1/receivables/{receivable_id}/payments",
            headers=auth(token, "mcp-rcv-equiv-pay-rest-0001"),
            json=_payment_payload("20.00"),
        )
        assert rest_pay.status_code == 201, rest_pay.text
        assert rest_pay.json()["openAmount"] == "40.00"

        async with mcp_session(token) as session:
            listed = await session.call_tool("receivables.list", {})
            assert listed.isError is False
            item = next(
                row for row in listed.structuredContent["result"] if row["id"] == receivable_id
            )
            assert item["openAmount"] == "40.00"
            assert item["status"] == "PARTIAL"


async def test_mcp_record_payment_rejects_overapplication_no_movement_created(client) -> None:
    """Un cobro que excede el saldo abierto falla y no crea ningun Movement."""

    receivable_id, _masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-over",
        sequential="000000963",
        total=Decimal("50.00"),
    )
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:write", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-rcv-over-enable-0001")

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool(
            "receivables.record_payment",
            {
                "receivableId": receivable_id,
                "payment": _payment_payload("50.01"),
                "idempotencyKey": "mcp-rcv-over-pay-0001",
            },
        )
        assert result.isError is True
        assert "exceeds open balance" in result.content[0].text

    async with SessionFactory() as db_session:
        movement_count = await db_session.scalar(
            select(func.count())
            .select_from(Movement)
            .where(Movement.receivable_id == uuid.UUID(receivable_id))
        )
    assert movement_count == 0

    rest_get = await client.get(f"/api/v1/receivables/{receivable_id}", headers=auth(token))
    assert rest_get.json()["openAmount"] == "50.00"
    assert rest_get.json()["status"] == "OPEN"


async def test_mcp_receivables_write_and_notify_blocked_by_kill_switch_but_not_list(
    client,
) -> None:
    """El kill switch bloquea escrituras/efecto externo pero nunca la lectura."""

    receivable_id, _masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-kill",
        sequential="000000964",
        total=Decimal("80.00"),
    )
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:write", "receivables:notify"],
    )

    # AutomationSettings.writes_enabled defaults to False (ver conftest).
    async with mcp_lifespan(), mcp_session(token) as session:
        listed = await session.call_tool("receivables.list", {})
        assert listed.isError is False

        blocked_pay = await session.call_tool(
            "receivables.record_payment",
            {
                "receivableId": receivable_id,
                "payment": _payment_payload("10.00"),
                "idempotencyKey": "mcp-rcv-kill-pay-0001",
            },
        )
        assert blocked_pay.isError is True
        assert "Automation writes are disabled" in blocked_pay.content[0].text

        blocked_reminder = await session.call_tool(
            "receivables.send_reminder",
            {
                "receivableId": receivable_id,
                "reminder": {},
                "idempotencyKey": "mcp-rcv-kill-remind-0001",
            },
        )
        assert blocked_reminder.isError is True
        assert "Automation writes are disabled" in blocked_reminder.content[0].text


async def test_mcp_send_reminder_blocked_then_allowed_after_enabling_writes(client) -> None:
    """`send_reminder` respeta el kill switch y, habilitado, crea un CollectionReminder."""

    receivable_id, masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-remind",
        sequential="000000967",
        total=Decimal("45.00"),
    )
    write_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["parties:write", "receivables:notify", "automation:write"],
    )
    party_update = await client.put(
        f"/api/v1/parties/{masters['party_id']}",
        headers=auth(write_token, "mcp-rcv-remind-party-0001"),
        json={
            "name": "Cliente Facturable",
            "identificationType": "CEDULA",
            "identificationNumber": "1790000001",
            "roles": ["CUSTOMER"],
            "email": "cliente@example.com",
        },
    )
    assert party_update.status_code == 200, party_update.text

    async with mcp_lifespan():
        async with mcp_session(write_token) as session:
            blocked = await session.call_tool(
                "receivables.send_reminder",
                {
                    "receivableId": receivable_id,
                    "reminder": {},
                    "idempotencyKey": "mcp-rcv-remind-0001",
                },
            )
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, write_token, "mcp-rcv-remind-enable-0001")

        async with mcp_session(write_token) as session:
            allowed = await session.call_tool(
                "receivables.send_reminder",
                {
                    "receivableId": receivable_id,
                    "reminder": {},
                    "idempotencyKey": "mcp-rcv-remind-0002",
                },
            )
            assert allowed.isError is False, allowed.content
            assert allowed.structuredContent["status"] == "PROCESSING"

    async with SessionFactory() as db_session:
        reminder_count = await db_session.scalar(
            select(func.count())
            .select_from(CollectionReminder)
            .where(CollectionReminder.tenant_id == TENANT_A)
        )
    assert reminder_count == 1


async def test_mcp_record_payment_idempotency_replay_does_not_duplicate_movement(client) -> None:
    receivable_id, _masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-idem",
        sequential="000000965",
        total=Decimal("60.00"),
    )
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:write", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-rcv-idem-enable-0001")

    payload = {
        "receivableId": receivable_id,
        "payment": _payment_payload("25.00"),
        "idempotencyKey": "mcp-rcv-idem-pay-0001",
    }
    async with mcp_lifespan(), mcp_session(token) as session:
        first = await session.call_tool("receivables.record_payment", payload)
        replay = await session.call_tool("receivables.record_payment", payload)
        assert first.isError is False, first.content
        assert replay.isError is False
        assert first.structuredContent == replay.structuredContent

    async with SessionFactory() as db_session:
        movement_count = await db_session.scalar(
            select(func.count())
            .select_from(Movement)
            .where(
                Movement.receivable_id == uuid.UUID(receivable_id),
                Movement.movement_type == "PAYMENT",
            )
        )
    assert movement_count == 1


async def test_mcp_record_payment_missing_scope_and_foreign_tenant(client) -> None:
    receivable_id, _masters = await _create_receivable(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-rcv-neg",
        sequential="000000966",
        total=Decimal("30.00"),
    )

    no_scope_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    foreign_token = await token_for(
        client, "b@iaerp.local", TENANT_B, ["receivables:write", "automation:write"]
    )
    # Habilitar writes en el tenant ajeno para descartar que el kill switch (y
    # no el aislamiento de tenant) sea la razon del rechazo.
    await _enable_automation_writes(client, foreign_token, "mcp-rcv-neg-enable-0001")

    async with mcp_lifespan():
        async with mcp_session(no_scope_token) as session:
            result = await session.call_tool(
                "receivables.record_payment",
                {
                    "receivableId": receivable_id,
                    "payment": _payment_payload("5.00"),
                    "idempotencyKey": "mcp-rcv-neg-pay-0001",
                },
            )
            assert result.isError is True
            assert "missing scope receivables:write" in result.content[0].text

        async with mcp_session(foreign_token) as session:
            result = await session.call_tool(
                "receivables.record_payment",
                {
                    "receivableId": receivable_id,
                    "payment": _payment_payload("5.00"),
                    "idempotencyKey": "mcp-rcv-neg-pay-0002",
                },
            )
            assert result.isError is True
            assert "Receivable not found" in result.content[0].text

    async with SessionFactory() as db_session:
        movement_count = await db_session.scalar(
            select(func.count())
            .select_from(Movement)
            .where(Movement.receivable_id == uuid.UUID(receivable_id))
        )
    assert movement_count == 0

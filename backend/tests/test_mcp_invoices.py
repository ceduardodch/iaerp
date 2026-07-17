"""FASE 6 (E7-03): tools MCP de facturacion (`invoices.*`, `credit_notes.*`).

Cubre, segun `docs/sprints/sprint-02.md` decision 9 y sus criterios de
aceptacion:

- Catalogo filtrado por scope: un token sin scopes de facturacion no ve las
  tools nuevas; con ellos las ve (`ScopedFastMCP.list_tools`).
- Equivalencia REST/MCP: un borrador creado por MCP se ve por REST (y
  viceversa) con los mismos totales, porque ambas superficies invocan
  exactamente los mismos casos de uso de `services/billing.py`.
- Kill switch: bloquea `invoices.create_draft`/`invoices.issue`/
  `credit_notes.create_and_issue`, pero nunca `invoices.get` (solo lectura).
- Idempotencia: repetir `idempotencyKey` en `invoices.create_draft` devuelve
  el mismo documento sin quemar un segundo secuencial; en `invoices.issue` no
  duplica el evento outbox `invoice.signed` ni los `DocumentArtifact`.
- Seguridad negativa: scope faltante -> error con el scope faltante;
  documento de otro tenant -> not found (nunca se filtra su existencia).

`invoices.issue` y `credit_notes.create_and_issue` firman XML y suben
artefactos a MinIO (via `services/billing.issue_document`), igual que
`test_invoice_issue_flow.py`/`test_billing_credit_note.py`: se omiten
automaticamente si MinIO no esta accesible en `localhost:9000`.

Nota de transporte: ``mcp.session_manager`` (instancia global de
``app.mcp.server``) solo puede ejecutar ``.run()`` una vez por instancia, y
ese ``.run()`` ocurre dentro del lifespan del ``app`` (``app/main.py``). Cada
test entra a ``mcp_lifespan()`` UNA sola vez y abre dentro tantas sesiones
MCP (con distintos tokens) como necesite; nunca anida un segundo
``lifespan_context`` en el mismo proceso de test.
"""

import socket
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import func, select
from starlette.routing import Mount

from app.db.session import SessionFactory
from app.main import app
from app.mcp.server import mcp
from app.models.billing import DocumentArtifact, SalesDocument
from app.models.platform import AuditEvent, OutboxEvent
from tests.test_billing_api import (
    TENANT_A,
    TENANT_B,
    _invoice_payload,
    _setup_billing_masters,
    auth,
    token_for,
)


def _minio_is_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 9000), timeout=1):
            return True
    except OSError:
        return False


_MINIO_AVAILABLE = _minio_is_reachable()


def _replace_mcp_mount(fresh_mcp_app) -> None:
    """Sustituye el ``Mount`` de ``/mcp`` en ``app`` por uno recien creado.

    ``app/main.py`` monta ``mcp_http_app = mcp.streamable_http_app()`` UNA vez
    a nivel de modulo, y ese Starlette sub-app cierra sobre el
    ``StreamableHTTPSessionManager`` vigente en ese instante
    (``StreamableHTTPASGIApp(self._session_manager)``). Ese
    ``session_manager`` solo admite un `.run()` en toda su vida, asi que cada
    test que necesita su propio lifespan debe generar un sub-app fresco (con
    un session manager fresco) y reemplazar el ``Mount`` montado, o el
    segundo test del modulo revienta con
    ``RuntimeError: ... .run() can only be called once per instance``.
    """
    routes = app.router.routes
    for index, route in enumerate(routes):
        if isinstance(route, Mount) and route.path == "":
            routes[index] = Mount("/", app=fresh_mcp_app)
            return
    raise AssertionError("MCP mount not found on app.router.routes")


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    """Entra al lifespan del ``app``, con un ``StreamableHTTPSessionManager`` fresco.

    Ver ``_replace_mcp_mount``: recrea el sub-app MCP montado (con un session
    manager nuevo) antes de cada entrada al lifespan, porque ``mcp`` es un
    singleton a nivel de modulo (``app.mcp.server``) compartido por todos los
    tests del proceso y su session manager no se puede reutilizar entre
    tests.
    """
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


async def _setup_masters_and_invoice_scoped_token(
    client, *, tenant_id: uuid.UUID, email: str, key_prefix: str, extra_scopes: list[str]
) -> tuple[dict[str, str], str]:
    setup_token = await token_for(
        client,
        email,
        tenant_id,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup_token, key_prefix=key_prefix)
    invoices_token = await token_for(client, email, tenant_id, extra_scopes)
    return masters, invoices_token


async def test_mcp_invoices_catalog_filtered_by_scope(client) -> None:
    """Sin scopes de facturacion no aparecen; con ellos, las cuatro aparecen."""

    read_token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    full_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        [
            "context:read",
            "invoices:read",
            "invoices:write",
            "invoices:issue",
            "credit-notes:issue",
        ],
    )

    async with mcp_lifespan():
        async with mcp_session(read_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert "invoices.get" not in names
            assert "invoices.create_draft" not in names
            assert "invoices.issue" not in names
            assert "credit_notes.create_and_issue" not in names

        async with mcp_session(full_token) as session:
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "invoices.get",
                "invoices.create_draft",
                "invoices.issue",
                "credit_notes.create_and_issue",
            }.issubset(names)


async def test_mcp_invoices_get_requires_only_read_scope_and_is_not_gated_by_kill_switch(
    client,
) -> None:
    """`invoices.get` es solo lectura: no pasa por `_require_automation_writes`."""

    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-get",
        extra_scopes=["invoices:write", "invoices:read"],
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "mcp-get-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    # AutomationSettings.writes_enabled defaults to False (see conftest); the
    # kill switch must not block a pure read.
    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool("invoices.get", {"invoiceId": invoice_id})
        assert result.isError is False
        assert result.structuredContent["id"] == invoice_id
        assert result.structuredContent["subtotal"] == "100.00"
        assert result.structuredContent["total"] == "115.00"


async def test_mcp_invoices_get_missing_scope_and_foreign_tenant(client) -> None:
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-get-neg",
        extra_scopes=["invoices:write", "invoices:read"],
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "mcp-get-neg-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    no_scope_token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    other_tenant_token = await token_for(client, "b@iaerp.local", TENANT_B, ["invoices:read"])

    async with mcp_lifespan():
        async with mcp_session(no_scope_token) as session:
            result = await session.call_tool("invoices.get", {"invoiceId": invoice_id})
            assert result.isError is True
            assert "missing scope invoices:read" in result.content[0].text

        async with mcp_session(other_tenant_token) as session:
            result = await session.call_tool("invoices.get", {"invoiceId": invoice_id})
            assert result.isError is True
            assert "Sales document not found" in result.content[0].text


async def test_mcp_invoices_create_draft_blocked_by_kill_switch_but_not_get(client) -> None:
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-kill",
        extra_scopes=["invoices:write", "invoices:read", "automation:write"],
    )

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            blocked = await session.call_tool(
                "invoices.create_draft",
                {
                    "invoice": _invoice_payload(masters),
                    "idempotencyKey": "mcp-kill-draft-0001",
                },
            )
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, token, "mcp-kill-enable-0001")

        async with mcp_session(token) as session:
            allowed = await session.call_tool(
                "invoices.create_draft",
                {
                    "invoice": _invoice_payload(masters),
                    "idempotencyKey": "mcp-kill-draft-0002",
                },
            )
            assert allowed.isError is False
            assert allowed.structuredContent["status"] == "DRAFT"


async def test_mcp_create_draft_equivalence_with_rest_same_totals_both_ways(client) -> None:
    """Un borrador creado por MCP se lee por REST y viceversa, mismos totales."""

    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-equiv",
        extra_scopes=["invoices:write", "invoices:read", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-equiv-enable-0001")

    async with mcp_lifespan():
        # 1) Created via MCP, read via REST.
        async with mcp_session(token) as session:
            created = await session.call_tool(
                "invoices.create_draft",
                {
                    "invoice": _invoice_payload(masters),
                    "idempotencyKey": "mcp-equiv-draft-0001",
                },
            )
            assert created.isError is False
            mcp_document = created.structuredContent

        assert mcp_document["subtotal"] == "100.00"
        assert mcp_document["tax"] == "15.00"
        assert mcp_document["total"] == "115.00"

        rest_get = await client.get(
            f"/api/v1/invoices/{mcp_document['id']}", headers=auth(token)
        )
        assert rest_get.status_code == 200
        assert rest_get.json() == mcp_document

        # 2) Created via REST, read via MCP.
        rest_created = await client.post(
            "/api/v1/invoices",
            headers=auth(token, "mcp-equiv-draft-rest-0001"),
            json=_invoice_payload(masters),
        )
        assert rest_created.status_code == 201, rest_created.text
        rest_document = rest_created.json()

        async with mcp_session(token) as session:
            mcp_get = await session.call_tool(
                "invoices.get", {"invoiceId": rest_document["id"]}
            )
            assert mcp_get.isError is False
            assert mcp_get.structuredContent == rest_document

    # Sequentials are consecutive across both surfaces: no separate counters.
    assert int(rest_document["sequential"]) == int(mcp_document["sequential"]) + 1


async def test_mcp_invoices_create_draft_idempotency_replay_returns_same_document(
    client,
) -> None:
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-idem-draft",
        extra_scopes=["invoices:write", "invoices:read", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-idem-draft-enable-0001")

    payload = {
        "invoice": _invoice_payload(masters),
        "idempotencyKey": "mcp-idem-draft-0001",
    }
    async with mcp_lifespan(), mcp_session(token) as session:
        first = await session.call_tool("invoices.create_draft", payload)
        replay = await session.call_tool("invoices.create_draft", payload)
        assert first.isError is False
        assert replay.isError is False
        assert first.structuredContent == replay.structuredContent

    async with SessionFactory() as db_session:
        audit_count = await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == TENANT_A,
                AuditEvent.action == "invoice.draft_created",
                AuditEvent.idempotency_key == "mcp-idem-draft-0001",
            )
        )
        assert audit_count == 1


async def test_mcp_invoices_create_draft_missing_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read"])
    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool(
            "invoices.create_draft",
            {
                "invoice": _invoice_payload(
                    {
                        "party_id": str(uuid.uuid4()),
                        "establishment_id": str(uuid.uuid4()),
                        "emission_point_id": str(uuid.uuid4()),
                        "product_id": str(uuid.uuid4()),
                        "tax_code": "4",
                    }
                ),
                "idempotencyKey": "mcp-noscope-draft-0001",
            },
        )
        assert result.isError is True
        assert "missing scope invoices:write" in result.content[0].text


@pytest.mark.skipif(
    not _MINIO_AVAILABLE, reason="MinIO is not reachable at localhost:9000 in this environment"
)
async def test_mcp_invoices_issue_blocked_by_kill_switch_and_idempotent_when_allowed(
    client,
) -> None:
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-issue",
        extra_scopes=[
            "invoices:write",
            "invoices:read",
            "invoices:issue",
            "automation:write",
        ],
    )
    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "mcp-issue-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            blocked = await session.call_tool(
                "invoices.issue",
                {"invoiceId": invoice_id, "idempotencyKey": "mcp-issue-attempt-0001"},
            )
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, token, "mcp-issue-enable-0001")

        async with mcp_session(token) as session:
            first = await session.call_tool(
                "invoices.issue",
                {"invoiceId": invoice_id, "idempotencyKey": "mcp-issue-issue-0001"},
            )
            replay = await session.call_tool(
                "invoices.issue",
                {"invoiceId": invoice_id, "idempotencyKey": "mcp-issue-issue-0001"},
            )
            assert first.isError is False, first.content
            assert replay.isError is False
            assert first.structuredContent == replay.structuredContent
            assert first.structuredContent["status"] == "PROCESSING"

        get_response = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
        assert get_response.status_code == 200
        signed = get_response.json()
        assert signed["status"] == "SIGNED"
        assert signed["accessKey"] is not None

    async with SessionFactory() as db_session:
        outbox_count = await db_session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == TENANT_A,
                OutboxEvent.event_type == "invoice.signed",
                OutboxEvent.aggregate_id == invoice_id,
            )
        )
        assert outbox_count == 1

        artifact_count = await db_session.scalar(
            select(func.count())
            .select_from(DocumentArtifact)
            .where(DocumentArtifact.sales_document_id == uuid.UUID(invoice_id))
        )
        assert artifact_count == 2


@pytest.mark.skipif(
    not _MINIO_AVAILABLE, reason="MinIO is not reachable at localhost:9000 in this environment"
)
async def test_mcp_credit_notes_create_and_issue_equivalence_and_idempotency(client) -> None:
    """`credit_notes.create_and_issue` reutiliza el mismo pipeline que REST."""

    from app.integrations.sri.simulator import SimulatorSRIClient, get_store
    from app.workers.outbox import claim_outbox_batch
    from app.workers.sri_transmission import handle_invoice_signed

    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="mcp-cn",
        extra_scopes=[
            "invoices:write",
            "invoices:read",
            "invoices:issue",
            "credit-notes:issue",
            "automation:write",
        ],
    )
    await _enable_automation_writes(client, token, "mcp-cn-enable-0001")

    draft = await client.post(
        "/api/v1/invoices",
        headers=auth(token, "mcp-cn-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    issue_response = await client.post(
        f"/api/v1/invoices/{invoice_id}/issue",
        headers=auth(token, "mcp-cn-issue-0001"),
    )
    assert issue_response.status_code == 202, issue_response.text

    async with SessionFactory() as db_session, db_session.begin():
        messages = await claim_outbox_batch(db_session)
    matching = [
        message
        for message in messages
        if message.event_type == "invoice.signed" and message.aggregate_id == invoice_id
    ]
    assert len(matching) == 1
    message = matching[0]

    get_store().reset()
    async with SessionFactory() as db_session:
        await handle_invoice_signed(db_session, message, sri_client=SimulatorSRIClient())
        await db_session.commit()
    async with SessionFactory() as db_session:
        await handle_invoice_signed(db_session, message, sri_client=SimulatorSRIClient())
        await db_session.commit()

    authorized = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    assert authorized.json()["status"] == "AUTHORIZED", authorized.text

    credit_note_payload = {
        "invoiceId": invoice_id,
        "reason": "Devolucion parcial via MCP",
        "lines": [
            {
                "productId": masters["product_id"],
                "description": "Consultoria julio",
                "quantity": "1",
                "unitPrice": "50.000000",
                "discount": "0.00",
                "taxCode": masters["tax_code"],
            }
        ],
    }

    async with mcp_lifespan(), mcp_session(token) as session:
        first = await session.call_tool(
            "credit_notes.create_and_issue",
            {"creditNote": credit_note_payload, "idempotencyKey": "mcp-cn-issue-0001"},
        )
        replay = await session.call_tool(
            "credit_notes.create_and_issue",
            {"creditNote": credit_note_payload, "idempotencyKey": "mcp-cn-issue-0001"},
        )
        assert first.isError is False, first.content
        assert replay.isError is False
        assert first.structuredContent == replay.structuredContent
        credit_note_id = first.structuredContent["result"]["sales_document_id"]

    rest_get = await client.get(f"/api/v1/invoices/{credit_note_id}", headers=auth(token))
    assert rest_get.status_code == 200
    credit_note_body = rest_get.json()
    assert credit_note_body["type"] == "CREDIT_NOTE"
    assert credit_note_body["status"] == "SIGNED"
    # 1 unit x $50 subtotal + 15% IVA = $57.50 (half the invoice's 2-unit total).
    assert credit_note_body["subtotal"] == "50.00"
    assert credit_note_body["tax"] == "7.50"
    assert credit_note_body["total"] == "57.50"

    async with SessionFactory() as db_session:
        outbox_count = await db_session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == TENANT_A,
                OutboxEvent.event_type == "invoice.signed",
                OutboxEvent.aggregate_id == credit_note_id,
            )
        )
        assert outbox_count == 1

        credit_note_count = await db_session.scalar(
            select(func.count())
            .select_from(SalesDocument)
            .where(SalesDocument.id == uuid.UUID(credit_note_id))
        )
        assert credit_note_count == 1


async def test_mcp_credit_notes_create_and_issue_missing_scope(client) -> None:
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:read", "invoices:write"]
    )
    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool(
            "credit_notes.create_and_issue",
            {
                "creditNote": {
                    "invoiceId": str(uuid.uuid4()),
                    "reason": "Sin scope",
                    "lines": [
                        {
                            "productId": str(uuid.uuid4()),
                            "description": "x",
                            "quantity": "1",
                            "unitPrice": "1.00",
                            "discount": "0.00",
                            "taxCode": "4",
                        }
                    ],
                },
                "idempotencyKey": "mcp-cn-noscope-0001",
            },
        )
        assert result.isError is True
        assert "missing scope credit-notes:issue" in result.content[0].text

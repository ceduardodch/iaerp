import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.main import app

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


async def token_for(client, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": "a@iaerp.local",
            "tenantId": str(TENANT_A),
            "scopes": scopes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key,
    }


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


async def test_mcp_transport_scopes_kill_switch_and_idempotency(client):
    read_token = await token_for(
        client,
        ["context:read", "parties:read"],
    )
    write_token = await token_for(
        client,
        [
            "automation:write",
            "context:read",
            "parties:read",
            "parties:write",
        ],
    )

    async with app.router.lifespan_context(app):
        async with mcp_session(read_token) as session:
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "context.get",
                "parties.search",
                "parties.create",
                "products.search",
                "products.create",
            }

            context_result = await session.call_tool("context.get", {})
            assert context_result.isError is False
            assert context_result.structuredContent["tenantId"] == str(TENANT_A)

            forbidden = await session.call_tool(
                "parties.create",
                {
                    "party": {
                        "name": "Blocked",
                        "identificationType": "RUC",
                        "identificationNumber": "1791111111001",
                        "roles": ["CUSTOMER"],
                    },
                    "idempotencyKey": "mcp-party-blocked-0001",
                },
            )
            assert forbidden.isError is True
            assert "missing scope parties:write" in forbidden.content[0].text

        async with mcp_session(write_token) as session:
            disabled = await session.call_tool(
                "parties.create",
                {
                    "party": {
                        "name": "Blocked by policy",
                        "identificationType": "RUC",
                        "identificationNumber": "1791111111002",
                        "roles": ["CUSTOMER"],
                    },
                    "idempotencyKey": "mcp-party-policy-0001",
                },
            )
            assert disabled.isError is True
            assert "Automation writes are disabled" in disabled.content[0].text

        enabled = await client.put(
            "/api/v1/automation/settings",
            headers=auth(write_token, "mcp-enable-writes-0001"),
            json={"writesEnabled": True, "dailyAmountLimit": "1000.00"},
        )
        assert enabled.status_code == 200

        async with mcp_session(write_token) as session:
            arguments = {
                "party": {
                    "name": "Cliente MCP",
                    "identificationType": "RUC",
                    "identificationNumber": "1791111111003",
                    "roles": ["CUSTOMER"],
                },
                "idempotencyKey": "mcp-party-create-0001",
            }
            created = await session.call_tool("parties.create", arguments)
            replay = await session.call_tool("parties.create", arguments)
            assert created.isError is False
            assert replay.isError is False
            assert created.structuredContent == replay.structuredContent

            search = await session.call_tool(
                "parties.search",
                {"query": "Cliente MCP", "role": "CUSTOMER"},
            )
            assert search.isError is False
            assert [item["name"] for item in search.structuredContent["result"]] == [
                "Cliente MCP"
            ]

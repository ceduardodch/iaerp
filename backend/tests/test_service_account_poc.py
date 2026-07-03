"""PoC automatizado de service accounts contra el stack local real (ADR 0009).

Cubre client credentials, expiracion, revocacion y rechazo inmediato de un
token todavia vigente. Requiere el stack de Compose corriendo con Keycloak y
la API en modo OIDC:

    AUTH_MODE=oidc docker compose up -d --wait
    IAERP_POC=1 uv run pytest tests/test_service_account_poc.py -q

Sin IAERP_POC=1 la suite se omite, por lo que no afecta la corrida normal.
"""

import asyncio
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import jwt
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

pytestmark = pytest.mark.skipif(
    os.environ.get("IAERP_POC") != "1",
    reason="PoC en vivo deshabilitado; exportar IAERP_POC=1 con el stack OIDC arriba",
)

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.environ.get("KEYCLOAK_REALM", "iaerp")
API_URL = os.environ.get("IAERP_API_URL", "http://localhost:8000")
MCP_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/mcp")

INTEGRATION_CLIENT_ID = os.environ.get("KEYCLOAK_INTEGRATION_CLIENT_ID", "iaerp-integration-cli")
OWNER_USERNAME = os.environ.get("KEYCLOAK_TEST_USERNAME", "owner")
OWNER_PASSWORD = os.environ.get("KEYCLOAK_TEST_PASSWORD", "DemoPass123!")
DEMO_ORGANIZATION_ALIAS = os.environ.get("KEYCLOAK_DEMO_ORG_ALIAS", "iaerp-norte")
DEMO_TENANT_ID = "11111111-1111-4111-8111-111111111111"

AGENT_NORTE_CLIENT_ID = "iaerp-agent-norte"
AGENT_NORTE_SECRET = os.environ.get(
    "KEYCLOAK_AGENT_NORTE_SECRET",
    "local-only-agent-norte-secret",
)
PROVISIONER_CLIENT_ID = os.environ.get("KEYCLOAK_ADMIN_CLIENT_ID", "iaerp-provisioner")
PROVISIONER_SECRET = os.environ.get(
    "KEYCLOAK_ADMIN_CLIENT_SECRET",
    "local-only-provisioner-secret",
)

MAX_TOKEN_LIFESPAN_SECONDS = 300

TOKEN_ENDPOINT = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
ADMIN_CLIENTS_ENDPOINT = f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients"


def _decode_unverified(access_token: str) -> dict[str, Any]:
    return jwt.decode(
        access_token,
        options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
    )


def _idempotency_key() -> str:
    return secrets.token_hex(16)


async def _client_credentials(
    http: httpx.AsyncClient,
    client_id: str,
    client_secret: str,
) -> httpx.Response:
    return await http.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


async def _owner_api_token(http: httpx.AsyncClient) -> str:
    response = await http.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "password",
            "client_id": INTEGRATION_CLIENT_ID,
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
            "scope": f"openid organization:{DEMO_ORGANIZATION_ALIAS}",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def _admin_token(http: httpx.AsyncClient) -> str:
    response = await _client_credentials(http, PROVISIONER_CLIENT_ID, PROVISIONER_SECRET)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def _create_service_account(
    http: httpx.AsyncClient,
    owner_token: str,
    *,
    name: str,
) -> dict[str, Any]:
    response = await http.post(
        f"{API_URL}/api/v1/service-accounts",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "Idempotency-Key": _idempotency_key(),
        },
        json={
            "name": name,
            "scopes": ["context:read", "parties:read"],
            "expiresAt": "2030-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _revoke_service_account(
    http: httpx.AsyncClient,
    owner_token: str,
    account_id: str,
) -> httpx.Response:
    return await http.delete(
        f"{API_URL}/api/v1/service-accounts/{account_id}",
        headers={
            "Authorization": f"Bearer {owner_token}",
            "Idempotency-Key": _idempotency_key(),
        },
    )


@asynccontextmanager
async def _mcp_session(access_token: str) -> AsyncIterator[ClientSession]:
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    ) as http:
        async with streamable_http_client(
            MCP_URL,
            http_client=http,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def _mcp_call(access_token: str, tool: str, arguments: dict[str, Any]) -> CallToolResult:
    async with _mcp_session(access_token) as session:
        return await session.call_tool(tool, arguments)


async def _mcp_initialize_status(http: httpx.AsyncClient, access_token: str) -> int:
    response = await http.post(
        MCP_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "iaerp-poc", "version": "0"},
            },
        },
    )
    return response.status_code


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=15) as client:
        ready = await client.get(f"{API_URL}/health/ready")
        discovery = await client.get(
            f"{KEYCLOAK_URL}/realms/{REALM}/.well-known/openid-configuration"
        )
        if ready.status_code != 200 or discovery.status_code != 200:
            pytest.fail(
                "El PoC requiere el stack local arriba (API y Keycloak). "
                "Ejecutar: AUTH_MODE=oidc docker compose up -d --wait"
            )
        yield client


async def test_client_credentials_claims_lifespan_and_tenant_binding(
    http: httpx.AsyncClient,
) -> None:
    response = await _client_credentials(http, AGENT_NORTE_CLIENT_ID, AGENT_NORTE_SECRET)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] <= MAX_TOKEN_LIFESPAN_SECONDS

    claims = _decode_unverified(body["access_token"])
    assert claims["azp"] == AGENT_NORTE_CLIENT_ID
    audience = claims["aud"]
    assert audience == MCP_URL or (isinstance(audience, list) and MCP_URL in audience)
    assert claims["exp"] - claims["iat"] <= MAX_TOKEN_LIFESPAN_SECONDS

    if await _mcp_initialize_status(http, body["access_token"]) == 401:
        pytest.fail(
            "La API rechazo un token recien emitido por Keycloak; "
            "verificar que el stack corre con AUTH_MODE=oidc"
        )

    result = await _mcp_call(body["access_token"], "context.get", {})
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["tenantId"] == DEMO_TENANT_ID

    async with _mcp_session(body["access_token"]) as session:
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
    assert "context.get" in tool_names
    assert "parties.create" not in tool_names
    assert "products.create" not in tool_names


async def test_revocation_rejects_still_valid_token_and_new_issuance(
    http: httpx.AsyncClient,
) -> None:
    owner_token = await _owner_api_token(http)
    created = await _create_service_account(
        http,
        owner_token,
        name=f"PoC Revocacion {uuid.uuid4().hex[:8]}",
    )
    account = created["account"]
    client_id = account["clientId"]
    client_secret = created["clientSecret"]

    issued = await _client_credentials(http, client_id, client_secret)
    assert issued.status_code == 200, issued.text
    agent_token = issued.json()["access_token"]

    before = await _mcp_call(agent_token, "context.get", {})
    assert before.isError is False

    revoked = await _revoke_service_account(http, owner_token, account["id"])
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["active"] is False

    claims = _decode_unverified(agent_token)
    assert claims["exp"] > time.time(), "El token debe seguir vigente para probar el rechazo"
    after = await _mcp_call(agent_token, "context.get", {})
    assert after.isError is True
    assert "Service account not found" in after.content[0].text  # type: ignore[union-attr]

    reissued = await _client_credentials(http, client_id, client_secret)
    assert reissued.status_code in (400, 401), reissued.text


async def test_expired_token_is_rejected(http: httpx.AsyncClient) -> None:
    owner_token = await _owner_api_token(http)
    created = await _create_service_account(
        http,
        owner_token,
        name=f"PoC Expiracion {uuid.uuid4().hex[:8]}",
    )
    account = created["account"]
    client_id = account["clientId"]
    client_secret = created["clientSecret"]

    try:
        admin_token = await _admin_token(http)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        lookup = await http.get(
            ADMIN_CLIENTS_ENDPOINT,
            headers=admin_headers,
            params={"clientId": client_id},
        )
        assert lookup.status_code == 200, lookup.text
        representation = lookup.json()[0]
        attributes = representation.get("attributes") or {}
        attributes["access.token.lifespan"] = "1"
        representation["attributes"] = attributes
        updated = await http.put(
            f"{ADMIN_CLIENTS_ENDPOINT}/{representation['id']}",
            headers=admin_headers,
            json=representation,
        )
        assert updated.status_code == 204, updated.text

        issued = await _client_credentials(http, client_id, client_secret)
        assert issued.status_code == 200, issued.text
        short_lived_token = issued.json()["access_token"]
        assert issued.json()["expires_in"] <= 1

        assert await _mcp_initialize_status(http, short_lived_token) != 401
        await asyncio.sleep(3)
        assert await _mcp_initialize_status(http, short_lived_token) == 401
    finally:
        await _revoke_service_account(http, owner_token, account["id"])

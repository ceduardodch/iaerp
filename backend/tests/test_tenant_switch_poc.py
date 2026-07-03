"""PoC automatizado del cambio de tenant OIDC multi-tenant (ADR 0009).

Comprueba contra el stack local real que un usuario multi-tenant solo cambia
de tenant mediante una nueva autorizacion con `organization:<alias>`, que un
token con varias organizaciones se rechaza y que un usuario sin membresia en
la organizacion no obtiene contexto. Requiere el stack de Compose con la API
en modo OIDC:

    AUTH_MODE=oidc docker compose up -d --wait
    IAERP_POC=1 uv run pytest tests/test_tenant_switch_poc.py -q

Sin IAERP_POC=1 la suite se omite, por lo que no afecta la corrida normal.
El recorrido equivalente por interfaz esta en `frontend/tests/oidc.spec.ts`
(E2E_OIDC=1).
"""

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import httpx
import jwt
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("IAERP_POC") != "1",
    reason="PoC en vivo deshabilitado; exportar IAERP_POC=1 con el stack OIDC arriba",
)

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.environ.get("KEYCLOAK_REALM", "iaerp")
API_URL = os.environ.get("IAERP_API_URL", "http://localhost:8000")
TOKEN_ENDPOINT = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
APP_DATABASE_DSN = os.environ.get(
    "IAERP_POC_DATABASE_DSN",
    "postgresql://iaerp:iaerp-local-only@localhost:55432/iaerp",  # pragma: allowlist secret
)

INTEGRATION_CLIENT_ID = os.environ.get("KEYCLOAK_INTEGRATION_CLIENT_ID", "iaerp-integration-cli")
OWNER_USERNAME = os.environ.get("KEYCLOAK_TEST_USERNAME", "owner")
OWNER_PASSWORD = os.environ.get("KEYCLOAK_TEST_PASSWORD", "DemoPass123!")
SINGLE_TENANT_USERNAME = os.environ.get("KEYCLOAK_OPERATOR_USERNAME", "operator.norte")
NO_MEMBERSHIP_USERNAME = os.environ.get("KEYCLOAK_NO_MEMBERSHIP_USERNAME", "without.membership")
LOCAL_USER_PASSWORD = os.environ.get("KEYCLOAK_LOCAL_USER_PASSWORD", "LocalPass123!")

NORTE = {
    "alias": "iaerp-norte",
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "organization_id": "33333333-3333-4333-8333-333333333333",
    "ruc": "1791234502001",
}
SUR = {
    "alias": "iaerp-sur",
    "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "organization_id": "abababab-abab-4bab-8bab-abababababab",
    "ruc": "1795432104001",
}


def _decode_unverified(access_token: str) -> dict[str, Any]:
    return jwt.decode(
        access_token,
        options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
    )


async def _password_grant(
    http: httpx.AsyncClient,
    *,
    username: str,
    password: str,
    scope: str,
) -> str:
    response = await http.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "password",
            "client_id": INTEGRATION_CLIENT_ID,
            "username": username,
            "password": password,
            "scope": scope,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def _get_context(http: httpx.AsyncClient, access_token: str) -> httpx.Response:
    return await http.get(
        f"{API_URL}/api/v1/context",
        headers={"Authorization": f"Bearer {access_token}"},
    )


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


async def test_multi_tenant_user_switches_context_via_new_authorization(
    http: httpx.AsyncClient,
) -> None:
    for organization, expected_roles in ((NORTE, {"owner", "admin"}), (SUR, {"viewer"})):
        token = await _password_grant(
            http,
            username=OWNER_USERNAME,
            password=OWNER_PASSWORD,
            scope=f"openid organization:{organization['alias']}",
        )
        claims = _decode_unverified(token)
        assert set(claims["organization"]) == {organization["alias"]}
        assert claims["organization"][organization["alias"]]["id"] == (
            organization["organization_id"]
        )

        response = await _get_context(http, token)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tenantId"] == organization["tenant_id"]
        assert body["ruc"] == organization["ruc"]
        assert set(body["roles"]) == expected_roles


async def test_token_with_multiple_organizations_is_rejected(http: httpx.AsyncClient) -> None:
    token = await _password_grant(
        http,
        username=OWNER_USERNAME,
        password=OWNER_PASSWORD,
        scope="openid organization:*",
    )
    claims = _decode_unverified(token)
    assert set(claims["organization"]) == {NORTE["alias"], SUR["alias"]}

    response = await _get_context(http, token)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Token must contain exactly one organization"


async def test_user_without_organization_membership_gets_no_tenant_context(
    http: httpx.AsyncClient,
) -> None:
    cases = (
        # Miembro solo de Norte pidiendo Sur: Keycloak omite el scope y el
        # token queda sin claim de organizacion.
        (SINGLE_TENANT_USERNAME, SUR["alias"]),
        # Usuario sin ninguna organizacion.
        (NO_MEMBERSHIP_USERNAME, NORTE["alias"]),
    )
    for username, alias in cases:
        token = await _password_grant(
            http,
            username=username,
            password=LOCAL_USER_PASSWORD,
            scope=f"openid organization:{alias}",
        )
        claims = _decode_unverified(token)
        assert "organization" not in claims

        response = await _get_context(http, token)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == "Token must contain exactly one organization"


async def test_revoked_membership_blocks_still_valid_token(http: httpx.AsyncClient) -> None:
    """ADR 0009 punto 7: revocar la membresia bloquea aunque el token no expire."""
    token = await _password_grant(
        http,
        username=OWNER_USERNAME,
        password=OWNER_PASSWORD,
        scope=f"openid organization:{SUR['alias']}",
    )
    before = await _get_context(http, token)
    assert before.status_code == 200, before.text

    connection = await asyncpg.connect(APP_DATABASE_DSN)
    try:
        updated = await connection.execute(
            """
            UPDATE memberships SET active = FALSE
            WHERE tenant_id = $1
              AND user_id = (SELECT id FROM users WHERE email = 'owner@iaerp.local')
            """,
            uuid.UUID(SUR["tenant_id"]),
        )
        assert updated == "UPDATE 1", updated

        revoked = await _get_context(http, token)
        assert revoked.status_code == 404, revoked.text
        assert revoked.json()["detail"] == "Membership not found"
    finally:
        await connection.execute(
            """
            UPDATE memberships SET active = TRUE
            WHERE tenant_id = $1
              AND user_id = (SELECT id FROM users WHERE email = 'owner@iaerp.local')
            """,
            uuid.UUID(SUR["tenant_id"]),
        )
        await connection.close()

    restored = await _get_context(http, token)
    assert restored.status_code == 200, restored.text


async def test_api_and_mcp_audiences_are_not_interchangeable(http: httpx.AsyncClient) -> None:
    """ADR 0009: API y MCP usan audiences separadas y no aceptan tokens del otro."""
    api_token = await _password_grant(
        http,
        username=OWNER_USERNAME,
        password=OWNER_PASSWORD,
        scope=f"openid organization:{NORTE['alias']}",
    )
    mcp_rejects_api_token = await http.post(
        f"{API_URL}/mcp",
        headers={
            "Authorization": f"Bearer {api_token}",
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
    assert mcp_rejects_api_token.status_code == 401, mcp_rejects_api_token.text

    agent_response = await http.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "client_credentials",
            "client_id": "iaerp-agent-norte",
            "client_secret": os.environ.get(
                "KEYCLOAK_AGENT_NORTE_SECRET",
                "local-only-agent-norte-secret",
            ),
        },
    )
    assert agent_response.status_code == 200, agent_response.text
    mcp_token = agent_response.json()["access_token"]
    api_rejects_mcp_token = await _get_context(http, mcp_token)
    assert api_rejects_mcp_token.status_code == 401, api_rejects_mcp_token.text

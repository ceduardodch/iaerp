import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
API_URL = os.getenv("IAERP_API_URL", "http://localhost:8000")
MCP_URL = os.getenv("MCP_SERVER_URL", f"{API_URL}/mcp")
CLIENT_ID = os.getenv("KEYCLOAK_INTEGRATION_CLIENT_ID", "iaerp-integration-cli")
USERNAME = os.getenv("KEYCLOAK_TEST_USERNAME", "owner")
PASSWORD = os.getenv("KEYCLOAK_TEST_PASSWORD", "DemoPass123!")


def exception_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return " ".join(exception_text(item) for item in exc.exceptions)
    return str(exc)


async def issue_user_token(client: httpx.AsyncClient) -> str:
    response = await client.post(
        f"{KEYCLOAK_URL}/realms/iaerp/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": USERNAME,
            "password": PASSWORD,
            "scope": (
                "openid organization:iaerp-norte context:read "
                "service-accounts:read service-accounts:write"
            ),
        },
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


async def issue_service_token(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
) -> httpx.Response:
    return await client.post(
        f"{KEYCLOAK_URL}/realms/iaerp/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


@asynccontextmanager
async def mcp_session(token: str) -> AsyncIterator[ClientSession]:
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    ) as http_client:
        async with streamable_http_client(
            MCP_URL,
            http_client=http_client,
            terminate_on_close=False,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


async def main() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        user_token = await issue_user_token(client)
        suffix = uuid.uuid4().hex
        created = await client.post(
            f"{API_URL}/api/v1/service-accounts",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Idempotency-Key": f"oidc-service-create-{suffix}",
            },
            json={
                "name": f"OIDC runtime {suffix[:8]}",
                "scopes": ["context:read", "parties:read"],
                "expiresAt": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            },
        )
        created.raise_for_status()
        body = created.json()
        account = body["account"]
        service_token_response = await issue_service_token(
            client,
            client_id=account["clientId"],
            client_secret=body["clientSecret"],
        )
        service_token_response.raise_for_status()
        service_token = str(service_token_response.json()["access_token"])

        async with mcp_session(service_token) as session:
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if tool_names != {"context.get", "parties.search"}:
                raise RuntimeError(f"Unexpected service-account tools: {sorted(tool_names)}")
            context = await session.call_tool("context.get", {})
            if context.isError:
                raise RuntimeError("Service account could not read its tenant context")
            if (
                context.structuredContent is None
                or context.structuredContent.get("name") != "IAERP Demo Norte"
            ):
                raise RuntimeError("Service account resolved the wrong tenant")

        revoked = await client.delete(
            f"{API_URL}/api/v1/service-accounts/{account['id']}",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Idempotency-Key": f"oidc-service-revoke-{suffix}",
            },
        )
        revoked.raise_for_status()
        if revoked.json()["active"]:
            raise RuntimeError("Revoked service account remained active")

        try:
            async with mcp_session(service_token) as session:
                revoked_tools = await session.list_tools()
                denied = await session.call_tool("context.get", {})
                denied_text = " ".join(
                    item.text for item in denied.content if hasattr(item, "text")
                )
                rejected_existing_token = (
                    revoked_tools.tools == []
                    and denied.isError
                    and "Authorization failed" in denied_text
                )
        except Exception as exc:
            rejected_existing_token = (
                "Authorization failed: Service account not found" in exception_text(exc)
            )
        if not rejected_existing_token:
            raise RuntimeError("MCP accepted a token after service-account revocation")

        rejected_new_token = await issue_service_token(
            client,
            client_id=account["clientId"],
            client_secret=body["clientSecret"],
        )
        if rejected_new_token.status_code < 400:
            raise RuntimeError("Keycloak issued a token after service-account revocation")

    print(
        {
            "tenant": "IAERP Demo Norte",
            "tools": ["context.get", "parties.search"],
            "existing_token_rejected": True,
            "new_token_rejected": True,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())

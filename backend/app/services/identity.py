from typing import Any

import httpx
from fastapi import HTTPException

from app.core.config import get_settings

settings = get_settings()


def _admin_configured() -> bool:
    return all(
        (
            settings.OIDC_ADMIN_URL,
            settings.OIDC_ADMIN_CLIENT_ID,
            settings.OIDC_ADMIN_CLIENT_SECRET,
        )
    )


async def _admin_token(client: httpx.AsyncClient) -> str:
    if not _admin_configured():
        raise HTTPException(
            status_code=503,
            detail="Identity provisioning is not configured",
        )
    assert settings.OIDC_ADMIN_URL is not None
    assert settings.OIDC_ADMIN_CLIENT_ID is not None
    assert settings.OIDC_ADMIN_CLIENT_SECRET is not None
    response = await client.post(
        (
            f"{settings.OIDC_ADMIN_URL}/realms/{settings.OIDC_ADMIN_REALM}"
            "/protocol/openid-connect/token"
        ),
        data={
            "grant_type": "client_credentials",
            "client_id": settings.OIDC_ADMIN_CLIENT_ID,
            "client_secret": settings.OIDC_ADMIN_CLIENT_SECRET.get_secret_value(),
        },
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Identity provider rejected provisioning")
    return str(response.json()["access_token"])


def _client_representation(
    *,
    client_id: str,
    client_secret: str,
    name: str,
    scopes: list[str],
) -> dict[str, Any]:
    return {
        "clientId": client_id,
        "name": name,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "secret": client_secret,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "defaultClientScopes": sorted(set(scopes)),
        "optionalClientScopes": [],
        "protocolMappers": [
            {
                "name": "iaerp-mcp-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.custom.audience": settings.OIDC_MCP_AUDIENCE,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            }
        ],
    }


async def provision_service_account(
    *,
    client_id: str,
    client_secret: str,
    name: str,
    scopes: list[str],
) -> None:
    if settings.AUTH_MODE == "dev":
        return
    async with httpx.AsyncClient(timeout=15) as client:
        token = await _admin_token(client)
        assert settings.OIDC_ADMIN_URL is not None
        response = await client.post(
            (f"{settings.OIDC_ADMIN_URL}/admin/realms/{settings.OIDC_ADMIN_REALM}/clients"),
            headers={"Authorization": f"Bearer {token}"},
            json=_client_representation(
                client_id=client_id,
                client_secret=client_secret,
                name=name,
                scopes=scopes,
            ),
        )
        if response.status_code != 201:
            raise HTTPException(
                status_code=502,
                detail="Identity provider could not create service account",
            )


async def _find_client(
    client: httpx.AsyncClient,
    *,
    token: str,
    client_id: str,
) -> dict[str, Any] | None:
    assert settings.OIDC_ADMIN_URL is not None
    response = await client.get(
        (f"{settings.OIDC_ADMIN_URL}/admin/realms/{settings.OIDC_ADMIN_REALM}/clients"),
        headers={"Authorization": f"Bearer {token}"},
        params={"clientId": client_id},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Identity provider lookup failed")
    matches = [
        item
        for item in response.json()
        if isinstance(item, dict) and item.get("clientId") == client_id
    ]
    return matches[0] if matches else None


async def disable_service_account(client_id: str) -> None:
    if settings.AUTH_MODE == "dev":
        return
    async with httpx.AsyncClient(timeout=15) as client:
        token = await _admin_token(client)
        representation = await _find_client(client, token=token, client_id=client_id)
        if representation is None:
            return
        representation["enabled"] = False
        assert settings.OIDC_ADMIN_URL is not None
        response = await client.put(
            (
                f"{settings.OIDC_ADMIN_URL}/admin/realms/{settings.OIDC_ADMIN_REALM}"
                f"/clients/{representation['id']}"
            ),
            headers={"Authorization": f"Bearer {token}"},
            json=representation,
        )
        if response.status_code != 204:
            raise HTTPException(
                status_code=502,
                detail="Identity provider could not revoke service account",
            )


async def delete_service_account(client_id: str) -> None:
    if settings.AUTH_MODE == "dev":
        return
    async with httpx.AsyncClient(timeout=15) as client:
        token = await _admin_token(client)
        representation = await _find_client(client, token=token, client_id=client_id)
        if representation is None:
            return
        assert settings.OIDC_ADMIN_URL is not None
        await client.delete(
            (
                f"{settings.OIDC_ADMIN_URL}/admin/realms/{settings.OIDC_ADMIN_REALM}"
                f"/clients/{representation['id']}"
            ),
            headers={"Authorization": f"Bearer {token}"},
        )

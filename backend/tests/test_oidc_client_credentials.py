import json

import httpx

from app.integrations.oidc_client_credentials import ClientCredentialsToken


async def test_client_credentials_refreshes_before_expiry_and_retries_one_401() -> None:
    token_requests = 0
    api_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/token":
            token_requests += 1
            return httpx.Response(
                200,
                json={"access_token": f"short-token-{token_requests}", "expires_in": 60},
            )
        api_tokens.append(request.headers["Authorization"])
        if len(api_tokens) == 1:
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json={"ok": True})

    credentials = ClientCredentialsToken(
        "https://auth.example/token",
        "crm-agent",
        "secret-kept-in-memory",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.example",
    ) as client:
        response = await credentials.request(client, "GET", "/api/v1/crm/leads")

    assert response.status_code == 200
    assert token_requests == 2
    assert api_tokens == ["Bearer short-token-1", "Bearer short-token-2"]
    assert "secret-kept-in-memory" not in json.dumps(response.json())


async def test_client_credentials_reuses_token_until_refresh_window() -> None:
    token_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path == "/token":
            token_requests += 1
            return httpx.Response(200, json={"access_token": "short-token", "expires_in": 60})
        return httpx.Response(200, json={"ok": True})

    credentials = ClientCredentialsToken(
        "https://auth.example/token",
        "crm-agent",
        "secret-kept-in-memory",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.example",
    ) as client:
        await credentials.request(client, "GET", "/first")
        await credentials.request(client, "GET", "/second")

    assert token_requests == 1

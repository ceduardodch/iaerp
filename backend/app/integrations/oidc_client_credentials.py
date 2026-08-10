import time
from typing import Any

import httpx


class ClientCredentialsToken:
    """Token corto renovable para una cuenta de servicio OIDC."""

    def __init__(self, token_url: str, client_id: str, client_secret: str) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: str | None = None
        self.expires_at = 0.0

    async def get(self, client: httpx.AsyncClient, *, refresh: bool = False) -> str:
        if not refresh and self.access_token and time.monotonic() < self.expires_at:
            return self.access_token
        response = await client.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(token, str) or not token:
            raise RuntimeError("El proveedor de identidad no devolvio access_token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise RuntimeError("El proveedor de identidad no devolvio expires_in valido")
        self.access_token = token
        self.expires_at = time.monotonic() + max(1, expires_in - 30)
        return token

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        async def send(*, refresh: bool) -> httpx.Response:
            token = await self.get(client, refresh=refresh)
            headers = dict(kwargs.get("headers", {}))
            headers["Authorization"] = f"Bearer {token}"
            return await client.request(method, path, **{**kwargs, "headers": headers})

        response = await send(refresh=False)
        return await send(refresh=True) if response.status_code == 401 else response

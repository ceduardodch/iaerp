import importlib.util
from pathlib import Path

import httpx

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "load_prospects_to_crm.py"
spec = importlib.util.spec_from_file_location("load_prospects_to_crm", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
prospects = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prospects)


async def test_service_account_token_renews_after_unauthorized_response() -> None:
    issued_tokens = ["first-token", "renewed-token"]
    authorizations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(prospects.TOKEN_ENDPOINT):
            return httpx.Response(
                200,
                json={"access_token": issued_tokens.pop(0), "expires_in": 300},
            )
        authorizations.append(request.headers["Authorization"])
        if len(authorizations) == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=[])

    token = prospects.ServiceAccountToken("client-id", "client-secret")
    async with httpx.AsyncClient(
        base_url="https://iaerp.b2b.com.ec",
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await token.request(
            client,
            "GET",
            "/api/v1/crm/leads",
            headers={"Idempotency-Key": "prospect-test-key"},
        )

    assert response.status_code == 200
    assert authorizations == ["Bearer first-token", "Bearer renewed-token"]

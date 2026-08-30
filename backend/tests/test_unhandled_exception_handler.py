"""Handler global de excepciones no manejadas (app/main.py).

Antes de esto, un 500 que no fuera ``IntegrityError`` se perdia en el
traceback de uvicorn sin ``correlationId`` ni forma de cruzarlo con logs. Este
handler responde un 500 estable y deja un log JSON estructurado con
timestamp, correlation_id, tenant pseudonimizado, actor y el tipo de evento.
"""

import hashlib
import json
import logging

import pytest_asyncio

from app import main as app_main
from app.services import ops_failures
from tests.conftest import USER_A
from tests.test_billing_api import TENANT_A, auth, token_for


@pytest_asyncio.fixture
async def client_allow_500():
    """Cliente que no relanza la excepcion de servidor, para leer la respuesta.

    ``ServerErrorMiddleware`` (Starlette) siempre relanza la excepcion despues
    de enviar la respuesta -- asi uvicorn la loguea en produccion -- y el
    ``ASGITransport`` de httpx la propaga de vuelta al test por defecto. Solo
    aqui, donde forzamos un 500 a proposito, hace falta desactivar eso.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as async_client:
        yield async_client


async def test_unhandled_exception_returns_stable_500(client_allow_500, monkeypatch) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ops_failures, "list_failures", _boom)

    token = await token_for(client_allow_500, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client_allow_500.get(
        "/api/v1/ops/failures",
        headers={**auth(token), "X-Correlation-Id": "corr-boom"},
    )

    assert response.status_code == 500, response.text
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["correlationId"] == "corr-boom"


async def test_unhandled_exception_logs_structured_json(
    client_allow_500, monkeypatch, caplog
) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ops_failures, "list_failures", _boom)

    token = await token_for(client_allow_500, "a@iaerp.local", TENANT_A, ["operations:read"])
    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = await client_allow_500.get(
            "/api/v1/ops/failures",
            headers={**auth(token), "X-Correlation-Id": "corr-boom-log"},
        )

    assert response.status_code == 500, response.text
    [record] = [r for r in caplog.records if r.name == "app.main"]
    payload = json.loads(record.message)

    assert payload["correlation_id"] == "corr-boom-log"
    assert payload["level"] == "error"
    assert payload["event"] == "RuntimeError"
    assert payload["path"] == "/api/v1/ops/failures"
    assert payload["actor"] == str(USER_A)
    assert payload["tenant"] == hashlib.sha256(str(TENANT_A).encode()).hexdigest()[:12]
    # No debe filtrar el UUID crudo del tenant en el log.
    assert str(TENANT_A) not in payload["tenant"]
    assert "timestamp" in payload


async def test_unhandled_exception_reports_to_error_tracking(
    client_allow_500, monkeypatch
) -> None:
    """Pendiente 9: el handler global debe reenviar el fallo a
    ``capture_exception`` (Sentry/GlitchTip) con el mismo correlation_id,
    tenant pseudonimizado y actor que ya loguea en JSON.
    """

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ops_failures, "list_failures", _boom)

    captured: list[dict] = []
    monkeypatch.setattr(
        app_main,
        "capture_exception",
        lambda exc, **kwargs: captured.append({"exc": exc, **kwargs}),
    )

    token = await token_for(client_allow_500, "a@iaerp.local", TENANT_A, ["operations:read"])
    response = await client_allow_500.get(
        "/api/v1/ops/failures",
        headers={**auth(token), "X-Correlation-Id": "corr-sentry"},
    )

    assert response.status_code == 500, response.text
    [call] = captured
    assert isinstance(call["exc"], RuntimeError)
    assert call["correlation_id"] == "corr-sentry"
    assert call["tenant_hash"] == hashlib.sha256(str(TENANT_A).encode()).hexdigest()[:12]
    assert call["actor_id"] == str(USER_A)

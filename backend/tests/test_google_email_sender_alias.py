"""Envío Gmail con alias autorizado sin exponer la cuenta conectada."""

import base64
import uuid
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.services import crm_integrations
from tests.test_billing_api import TENANT_A


@pytest.mark.asyncio
async def test_google_email_uses_configured_sender_alias(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_access_token(_session, _context):
        return SimpleNamespace(email="personal@b2b.com.ec"), "google-token"

    class FakeResponse:
        is_error = False

        @staticmethod
        def json() -> dict[str, str]:
            return {"id": "gmail-message-1", "threadId": "gmail-thread-1"}

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            assert timeout == 30

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, str]):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr(crm_integrations, "_google_access_token", fake_access_token)
    monkeypatch.setattr(crm_integrations.httpx, "AsyncClient", FakeClient)
    context = AuthContext(
        actor_id="tester@iaerp.local",
        actor_type="USER",
        tenant_id=TENANT_A,
        roles=frozenset(),
        scopes=frozenset({"invoices:write"}),
        token_id=str(uuid.uuid4()),
    )

    async with SessionFactory() as session:
        message_id = await crm_integrations.send_google_email(
            session,
            context,
            recipient="cliente@example.com",
            subject="Factura",
            message="Adjuntamos su factura.",
            sender_address="contabilidad@b2b.com.ec",
            sender_name="Contabilidad B2B",
            reply_to="contabilidad@b2b.com.ec",
        )

    assert message_id == "gmail-message-1"
    raw = str(captured["json"]["raw"])
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    email = BytesParser(policy=policy.default).parsebytes(decoded)
    assert email["From"] == "Contabilidad B2B <contabilidad@b2b.com.ec>"
    assert email["Reply-To"] == "contabilidad@b2b.com.ec"
    assert "personal@b2b.com.ec" not in decoded.decode()

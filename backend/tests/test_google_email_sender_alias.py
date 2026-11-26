"""Envío Gmail con alias autorizado sin exponer la cuenta conectada."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

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

@pytest.mark.parametrize(
    "alias,status,body,expected",
    [
        (None, 0, {}, None),
        ("PERSONAL@example.com", 0, {}, None),
        ("billing@example.com", 404, {}, "not found"),
        ("billing@example.com", 403, {}, "Reconnect"),
        ("billing@example.com", 503, {}, "Could not verify"),
        ("billing@example.com", 200, {"sendAsEmail": "billing@example.com",
                                      "verificationStatus": "pending"}, "not verified"),
        ("billing@example.com", 200, {"sendAsEmail": "other@example.com",
                                      "verificationStatus": "accepted"}, "not verified"),
    ],
)
async def test_configured_invoice_sender_must_be_accepted(
    monkeypatch, alias, status, body, expected
):
    mailbox = SimpleNamespace(
        id=uuid.uuid4(), refresh_token_encrypted=None, access_token_encrypted="synthetic",
        email="personal@example.com",
        scopes_granted=crm_integrations.GOOGLE_SCOPES.split(),
        token_expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    async def connected(session, context):
        return mailbox

    async def token(session, context):
        assert status != 0, "A primary mailbox does not need alias verification"
        return mailbox, "synthetic"

    def get(request):
        assert request.method == "GET"
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(get))

    monkeypatch.setattr(crm_integrations, "_connected_google_integration", connected)
    monkeypatch.setattr(crm_integrations, "_google_access_token", token)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    async with SessionFactory() as session:
        sender = await crm_integrations.configured_google_sender(session, None, alias=alias)
        if expected:
            with pytest.raises(HTTPException) as caught:
                await crm_integrations.verify_google_sender_alias(session, None, sender)
            assert expected in caught.value.detail
        else:
            await crm_integrations.verify_google_sender_alias(session, None, sender)
            assert sender.address.casefold() == mailbox.email.casefold()

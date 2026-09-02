"""Transporte Brevo, remitente por tenant y webhook de rebotes (F2).

Ninguna prueba abre red: el cliente de Brevo se ejercita contra un transporte
de ``httpx`` simulado, que es lo que permite verificar el cuerpo real que se
manda sin depender de credenciales.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.integrations.notifications.brevo import BrevoEmailSender, redact
from app.integrations.notifications.email_sender import EmailMessage, StubEmailSender
from app.models.notifications import NotificationChannelAccount, NotificationDelivery
from app.services.notifications import channels, webhooks

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")

# Claves ficticias de las pruebas. Se declaran una sola vez para que el literal
# no se repita por el archivo y el escaner de secretos tenga un solo lugar que
# revisar.
FAKE_API_KEY = "secret-key"  # pragma: allowlist secret
LEAKED_KEY = "xkeysib-abc123"  # pragma: allowlist secret
ECHOED_KEY = "xkeysib-super-secreta"  # pragma: allowlist secret

MESSAGE = EmailMessage(
    recipient="contadora@ejemplo.ec",
    subject="Aviso",
    body_text="cuerpo",
    body_html="<p>cuerpo</p>",
    sender_email="avisos@iaerp.b2b.com.ec",
    sender_name="BTOB SAS",
    reply_to="gerencia@btob.com.ec",
)


@pytest.fixture
def mock_brevo(monkeypatch: pytest.MonkeyPatch):
    """Sustituye ``httpx.AsyncClient`` por uno con transporte simulado."""

    def install(handler):
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def factory(**kwargs: object) -> httpx.AsyncClient:
            kwargs.pop("transport", None)
            return real_client(transport=transport, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    return install


# --------------------------------------------------------------------------
# Cliente Brevo
# --------------------------------------------------------------------------


async def test_brevo_sends_the_expected_payload_and_keeps_the_message_id(mock_brevo) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("api-key")
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"messageId": "<abc@brevo>"})

    mock_brevo(handler)
    result = await BrevoEmailSender(
        api_key=FAKE_API_KEY, base_url="https://api.brevo.test/v3"
    ).send(MESSAGE)

    assert result.status == "SENT"
    assert result.provider == "BREVO"
    assert result.provider_message_id == "<abc@brevo>"
    assert captured["url"] == "https://api.brevo.test/v3/smtp/email"
    assert captured["api_key"] == FAKE_API_KEY
    body = str(captured["body"])
    assert "contadora@ejemplo.ec" in body
    assert "avisos@iaerp.b2b.com.ec" in body
    assert "gerencia@btob.com.ec" in body


async def test_brevo_failure_does_not_raise_so_the_rest_still_receives(mock_brevo) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Invalid recipient"})

    mock_brevo(handler)
    result = await BrevoEmailSender(
        api_key=FAKE_API_KEY, base_url="https://api.brevo.test/v3"
    ).send(MESSAGE)

    assert result.status == "FAILED"
    assert result.provider_message_id is None
    assert "Invalid recipient" in (result.error_message or "")


async def test_brevo_network_error_is_reported_not_raised(mock_brevo) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    mock_brevo(handler)
    result = await BrevoEmailSender(
        api_key=FAKE_API_KEY, base_url="https://api.brevo.test/v3"
    ).send(MESSAGE)

    assert result.status == "FAILED"
    assert "ConnectError" in (result.error_message or "")


async def test_missing_message_id_is_left_empty_not_invented(mock_brevo) -> None:
    """Un id falso haria creer que se puede cruzar un rebote con este envio."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    mock_brevo(handler)
    result = await BrevoEmailSender(
        api_key=FAKE_API_KEY, base_url="https://api.brevo.test/v3"
    ).send(MESSAGE)

    assert result.status == "SENT"
    assert result.provider_message_id is None


@pytest.mark.parametrize(
    "raw",
    [
        f"HTTP 401: {{'api-key': '{LEAKED_KEY}'}}",
        f"Authorization: Bearer {LEAKED_KEY}",
        f"token={LEAKED_KEY}",
        f'HTTP 400: {{"message":"bad request","secret":"{LEAKED_KEY}"}}',
    ],
)
def test_errors_never_carry_the_credential(raw: str) -> None:
    cleaned = redact(raw)
    assert LEAKED_KEY not in cleaned
    assert "REDACTED" in cleaned


async def test_a_provider_error_echoing_the_key_never_reaches_the_logbook(mock_brevo) -> None:
    """La defensa que no depende de adivinar como escribio la clave el proveedor."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Un proveedor puede devolver la credencial dentro del error.
        return httpx.Response(401, text=f'{{"code":"unauthorized","key":"{ECHOED_KEY}"}}')

    mock_brevo(handler)
    result = await BrevoEmailSender(
        api_key=ECHOED_KEY, base_url="https://api.brevo.test/v3"
    ).send(MESSAGE)

    assert result.status == "FAILED"
    assert ECHOED_KEY not in (result.error_message or "")
    assert "REDACTED" in (result.error_message or "")


# --------------------------------------------------------------------------
# Resolucion de proveedor y remitente
# --------------------------------------------------------------------------


@pytest.fixture
def platform_brevo(monkeypatch: pytest.MonkeyPatch):
    """Simula tener la cuenta Brevo configurada en el servidor."""

    def configure(*, api_key: str | None = FAKE_API_KEY, sender: str | None = "avisos@iaerp.ec"):
        get_settings.cache_clear()
        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "BREVO_API_KEY",
            None if api_key is None else _Secret(api_key),
        )
        monkeypatch.setattr(settings, "BREVO_SENDER_EMAIL", sender)
        return settings

    yield configure
    get_settings.cache_clear()


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def test_without_platform_key_the_stub_stays_active(platform_brevo) -> None:
    platform_brevo(api_key=None)
    assert isinstance(channels.build_email_sender(), StubEmailSender)


def test_with_platform_key_brevo_takes_over(platform_brevo) -> None:
    platform_brevo()
    assert isinstance(channels.build_email_sender(), BrevoEmailSender)


async def test_status_explains_why_it_cannot_send_yet(platform_brevo) -> None:
    platform_brevo(api_key=None)
    async with SessionFactory() as session:
        status = await channels.channel_status(
            session, tenant_id=TENANT_A, company_name="Tenant A"
        )
    assert status.ready is False
    assert status.provider == "STUB"
    assert "BREVO_API_KEY" in (status.blocking_reason or "")


async def test_status_flags_a_missing_sender_address(platform_brevo) -> None:
    platform_brevo(sender=None)
    async with SessionFactory() as session:
        status = await channels.channel_status(
            session, tenant_id=TENANT_A, company_name="Tenant A"
        )
    assert status.ready is False
    assert "remitente" in (status.blocking_reason or "")


async def test_sender_defaults_to_the_company_name(platform_brevo) -> None:
    platform_brevo()
    async with SessionFactory() as session:
        identity = await channels.resolve_sender_identity(
            session, tenant_id=TENANT_A, company_name="BTOB SAS"
        )
    assert identity.name == "BTOB SAS"
    assert identity.email == "avisos@iaerp.ec"
    assert identity.reply_to is None


async def test_tenant_can_override_name_and_reply_to(platform_brevo) -> None:
    platform_brevo()
    async with SessionFactory() as session, session.begin():
        session.add(
            NotificationChannelAccount(
                tenant_id=TENANT_A,
                sender_name="Contabilidad BTOB",
                reply_to="contabilidad@btob.com.ec",
            )
        )
    async with SessionFactory() as session:
        identity = await channels.resolve_sender_identity(
            session, tenant_id=TENANT_A, company_name="BTOB SAS"
        )
    assert identity.name == "Contabilidad BTOB"
    assert identity.reply_to == "contabilidad@btob.com.ec"
    # El From sigue saliendo del dominio verificado de la plataforma.
    assert identity.email == "avisos@iaerp.ec"


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------


async def seed_delivery(*, message_id: str, status: str = "SENT") -> uuid.UUID:
    from app.models.notifications import NotificationEvent

    async with SessionFactory() as session, session.begin():
        event = NotificationEvent(
            tenant_id=TENANT_A,
            rule_type="IVA_DECLARACION",
            dedupe_key=f"test:{uuid.uuid4()}",
            scheduled_at=datetime.now(UTC),
            status="SENT",
            payload={},
        )
        session.add(event)
        await session.flush()
        delivery_row = NotificationDelivery(
            tenant_id=TENANT_A,
            event_id=event.id,
            recipient="contadora@ejemplo.ec",
            provider="BREVO",
            provider_message_id=message_id,
            status=status,
        )
        session.add(delivery_row)
        await session.flush()
        return delivery_row.id


async def delivery_status(delivery_id: uuid.UUID) -> str:
    async with SessionFactory() as session:
        row = await session.get(NotificationDelivery, delivery_id)
        assert row is not None
        return row.status


async def test_hard_bounce_marks_the_delivery() -> None:
    delivery_id = await seed_delivery(message_id="<abc@brevo>")
    async with SessionFactory() as session, session.begin():
        applied = await webhooks.process_payload(
            session,
            payload={
                "event": "hard_bounce",
                "message-id": "<abc@brevo>",
                "reason": "mailbox not found",
            },
        )
    assert applied == 1
    assert await delivery_status(delivery_id) == "BOUNCED"


async def test_delivered_after_a_bounce_does_not_undo_it() -> None:
    """El desenlace negativo manda: un `delivered` tardio no lo borra."""
    delivery_id = await seed_delivery(message_id="<abc@brevo>", status="BOUNCED")
    async with SessionFactory() as session, session.begin():
        applied = await webhooks.process_payload(
            session, payload={"event": "delivered", "message-id": "<abc@brevo>"}
        )
    assert applied == 0
    assert await delivery_status(delivery_id) == "BOUNCED"


async def test_unknown_message_ids_and_events_are_ignored() -> None:
    await seed_delivery(message_id="<abc@brevo>")
    async with SessionFactory() as session, session.begin():
        assert (
            await webhooks.process_payload(
                session, payload={"event": "delivered", "message-id": "<otro@brevo>"}
            )
            == 0
        )
        assert (
            await webhooks.process_payload(
                session, payload={"event": "opened", "message-id": "<abc@brevo>"}
            )
            == 0
        )


async def test_a_batch_of_events_is_accepted() -> None:
    first = await seed_delivery(message_id="<uno@brevo>")
    second = await seed_delivery(message_id="<dos@brevo>")
    async with SessionFactory() as session, session.begin():
        applied = await webhooks.process_payload(
            session,
            payload=[
                {"event": "delivered", "messageId": "<uno@brevo>"},
                {"event": "spam", "message-id": "<dos@brevo>"},
            ],
        )
    assert applied == 2
    assert await delivery_status(first) == "SENT"
    assert await delivery_status(second) == "COMPLAINED"


def test_webhook_token_is_rejected_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin token configurado, ningun POST debe poder tocar la bitacora."""
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "BREVO_WEBHOOK_TOKEN", None)
    assert webhooks.token_matches("cualquier-cosa") is False
    get_settings.cache_clear()


def test_webhook_token_must_match_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "BREVO_WEBHOOK_TOKEN", _Secret("token-correcto"))
    assert webhooks.token_matches("token-correcto") is True
    assert webhooks.token_matches("token-incorrecto") is False
    get_settings.cache_clear()


async def test_deliveries_are_not_shared_between_tenants() -> None:
    """Un id de mensaje solo puede tocar la entrega que lo genero."""
    delivery_id = await seed_delivery(message_id="<solo-mio@brevo>")
    async with SessionFactory() as session:
        rows = list(
            await session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.provider_message_id == "<solo-mio@brevo>"
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].id == delivery_id
    assert rows[0].tenant_id == TENANT_A


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


async def token_for(client, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": "a@iaerp.local", "tenantId": str(TENANT_A), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["accessToken"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_channel_status_endpoint_explains_the_blocker(client, platform_brevo) -> None:
    platform_brevo(api_key=None)
    token = await token_for(client, ["notifications:read"])
    response = await client.get("/api/v1/notifications/channel-account", headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is False
    assert body["provider"] == "STUB"
    assert "BREVO_API_KEY" in body["blockingReason"]


async def test_channel_status_requires_its_scope(client) -> None:
    token = await token_for(client, ["invoices:read"])
    response = await client.get("/api/v1/notifications/channel-account", headers=auth(token))
    assert response.status_code == 403, response.text


async def test_tenant_configures_its_sender_from_the_api(client, platform_brevo) -> None:
    platform_brevo()
    token = await token_for(client, ["notifications:read", "notifications:write"])
    response = await client.put(
        "/api/v1/notifications/channel-account",
        headers=auth(token),
        json={"senderName": "Contabilidad BTOB", "replyTo": "contabilidad@btob.com.ec"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["senderName"] == "Contabilidad BTOB"
    assert body["replyTo"] == "contabilidad@btob.com.ec"
    assert body["ready"] is True
    # El From sigue siendo el dominio verificado de la plataforma.
    assert body["senderEmail"] == "avisos@iaerp.ec"


async def test_test_send_refuses_while_the_channel_is_not_ready(client, platform_brevo) -> None:
    """Mejor un 422 explicito que un correo que nunca llega y nadie sabe por que."""
    platform_brevo(api_key=None)
    token = await token_for(client, ["notifications:write"])
    response = await client.post(
        "/api/v1/notifications/channel-account/test",
        headers=auth(token),
        json={"recipient": "yo@ejemplo.ec"},
    )
    assert response.status_code == 422, response.text
    assert "BREVO_API_KEY" in response.json()["detail"]


async def test_test_send_reaches_the_provider(client, platform_brevo, mock_brevo) -> None:
    platform_brevo()
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"messageId": "<prueba@brevo>"})

    mock_brevo(handler)
    token = await token_for(client, ["notifications:write"])
    response = await client.post(
        "/api/v1/notifications/channel-account/test",
        headers=auth(token),
        json={"recipient": "yo@ejemplo.ec"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SENT"
    assert body["providerMessageId"] == "<prueba@brevo>"
    assert "yo@ejemplo.ec" in str(captured["body"])


async def test_webhook_rejects_a_wrong_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "BREVO_WEBHOOK_TOKEN", _Secret("token-correcto"))
    await seed_delivery(message_id="<abc@brevo>")
    response = await client.post(
        "/api/v1/webhooks/brevo/token-incorrecto",
        json={"event": "hard_bounce", "message-id": "<abc@brevo>"},
    )
    assert response.status_code == 404, response.text
    get_settings.cache_clear()


async def test_webhook_applies_a_bounce_with_the_right_token(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "BREVO_WEBHOOK_TOKEN", _Secret("token-correcto"))
    delivery_id = await seed_delivery(message_id="<abc@brevo>")
    response = await client.post(
        "/api/v1/webhooks/brevo/token-correcto",
        json={"event": "hard_bounce", "message-id": "<abc@brevo>", "reason": "no existe"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"deliveriesUpdated": 1}
    assert await delivery_status(delivery_id) == "BOUNCED"
    get_settings.cache_clear()

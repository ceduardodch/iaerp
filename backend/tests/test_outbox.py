from datetime import UTC, datetime, timedelta

from conftest import TENANT_A
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.platform import DeadLetter, InboxEvent, OutboxEvent
from app.workers.outbox import OutboxMessage, consume_once, dispatch_outbox_once

settings = get_settings()


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[OutboxMessage] = []

    async def publish(self, message: OutboxMessage) -> None:
        self.messages.append(message)
        if self.fail:
            raise RuntimeError("broker unavailable with secret=redacted")


async def _create_outbox_event(client) -> None:
    token_response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": "a@iaerp.local",
            "tenantId": str(TENANT_A),
            "scopes": ["tags:write"],
        },
    )
    token = token_response.json()["accessToken"]
    response = await client.post(
        "/api/v1/tags",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "outbox-event-create-0001",
        },
        json={"name": "Important", "color": "#D95D39"},
    )
    assert response.status_code == 201


async def test_outbox_recovers_publish_crash_and_inbox_deduplicates(client):
    await _create_outbox_event(client)

    crashing = RecordingPublisher(fail=True)
    assert await dispatch_outbox_once(crashing) == 1
    first = crashing.messages[0]

    async with SessionFactory() as session, session.begin():
        entity = await session.get(OutboxEvent, first.event_id)
        assert entity is not None
        assert entity.published_at is None
        assert entity.lease_until is None
        assert entity.attempts == 1
        assert "broker unavailable" in entity.last_error
        entity.available_at = datetime.now(UTC) - timedelta(seconds=1)

    succeeding = RecordingPublisher()
    assert await dispatch_outbox_once(succeeding) == 1
    assert succeeding.messages[0].event_id == first.event_id
    assert succeeding.messages[0].tenant_id == TENANT_A

    handled_tenants = []

    async def handler(_session: AsyncSession, message: OutboxMessage) -> None:
        handled_tenants.append(message.tenant_id)

    assert await consume_once(
        consumer_name="test.consumer",
        message=succeeding.messages[0],
        handler=handler,
    )
    assert not await consume_once(
        consumer_name="test.consumer",
        message=succeeding.messages[0],
        handler=handler,
    )
    assert handled_tenants == [TENANT_A]

    async with SessionFactory() as session:
        entity = await session.get(OutboxEvent, first.event_id)
        assert entity is not None
        assert entity.published_at is not None
        assert await session.scalar(select(func.count()).select_from(InboxEvent)) == 1


async def test_outbox_moves_exhausted_event_to_dead_letter(client):
    await _create_outbox_event(client)
    async with SessionFactory() as session, session.begin():
        entity = await session.scalar(select(OutboxEvent))
        assert entity is not None
        entity.attempts = settings.OUTBOX_MAX_ATTEMPTS - 1

    publisher = RecordingPublisher(fail=True)
    assert await dispatch_outbox_once(publisher) == 1

    async with SessionFactory() as session:
        event = await session.scalar(select(OutboxEvent))
        dead_letter = await session.scalar(select(DeadLetter))
        assert event is not None
        assert event.dead_lettered_at is not None
        assert dead_letter is not None
        assert dead_letter.tenant_id == TENANT_A
        assert dead_letter.source_id == event.id
        assert dead_letter.attempts == settings.OUTBOX_MAX_ATTEMPTS
        assert "secret=[REDACTED]" in dead_letter.error
        assert "secret=redacted" not in dead_letter.error

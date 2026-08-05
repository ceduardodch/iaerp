import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.services import social_campaigns
from app.workers.outbox import OutboxMessage

CONSUMER_NAME = "iaerp.social-campaigns"


def _worker_context(message: OutboxMessage) -> AuthContext:
    return AuthContext(
        actor_id="campaign-worker",
        actor_type="SERVICE",
        tenant_id=message.tenant_id,
        roles=frozenset({"system"}),
        scopes=frozenset({"communications:write"}),
        token_id=str(message.event_id),
    )


async def handle_campaign_preparation(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    """Crea objetos pausados en Meta después de confirmar la intención."""

    if message.aggregate_type != "social_campaign":
        return
    try:
        campaign_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    await social_campaigns.apply_campaign_preparation(
        session,
        _worker_context(message),
        campaign_id,
    )


async def handle_campaign_activation(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    """Activa en Meta solo después de que la intención quedó en el outbox."""

    if message.aggregate_type != "social_campaign":
        return
    try:
        campaign_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    await social_campaigns.apply_campaign_activation(
        session,
        tenant_id=message.tenant_id,
        campaign_id=campaign_id,
    )


async def handle_campaign_pause(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    if message.aggregate_type != "social_campaign":
        return
    try:
        campaign_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    await social_campaigns.apply_campaign_pause(
        session,
        tenant_id=message.tenant_id,
        campaign_id=campaign_id,
    )


async def handle_campaign_policy(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    if message.aggregate_type != "social_campaign_policy":
        return
    await social_campaigns.apply_campaign_policy(session, tenant_id=message.tenant_id)

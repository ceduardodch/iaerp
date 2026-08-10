from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.platform import AutomationRateWindow, Tenant


async def consume_automation_rate(
    context: AuthContext,
    operation: str,
    *,
    limit: int,
) -> None:
    """Cuenta el intento en una transaccion propia, incluso si luego se rechaza."""
    now = datetime.now(UTC)
    exceeded: bool

    async with SessionFactory() as session, session.begin():
        await session.scalar(
            select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
        )
        window = await session.scalar(
            select(AutomationRateWindow)
            .where(
                AutomationRateWindow.tenant_id == context.tenant_id,
                AutomationRateWindow.actor_id == context.actor_id,
                AutomationRateWindow.tool_name == operation,
            )
            .with_for_update()
        )
        if window is None:
            window = AutomationRateWindow(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                tool_name=operation,
                window_started_at=now,
                attempt_count=1,
                updated_at=now,
            )
            session.add(window)
        else:
            started_at = window.window_started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            if started_at <= now - timedelta(minutes=1):
                window.window_started_at = now
                window.attempt_count = 1
            else:
                window.attempt_count += 1
            window.updated_at = now
        exceeded = window.attempt_count > limit
    if exceeded:
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this operation")

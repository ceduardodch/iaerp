"""Permissions shared by the native quick-entry catalog routes."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.core.ios_permissions import IOS_CLIENT_ID, IOS_INVOICE_WRITER_ROLES
from app.db.session import get_session
from app.models.platform import Membership, Tenant, User

CatalogSession = Annotated[AsyncSession, Depends(get_session)]
CatalogKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]


def require_catalog_creator(
    read_scope: str, write_scope: str
) -> Callable[..., Awaitable[AuthContext]]:
    async def authorize(
        context: Annotated[AuthContext, Depends(require_scopes(read_scope, write_scope))],
    ) -> AuthContext:
        if (
            context.client_id != IOS_CLIENT_ID
            or context.actor_type != "USER"
            or IOS_INVOICE_WRITER_ROLES.isdisjoint(context.roles)
        ):
            raise HTTPException(403, "Native catalog creation is not authorized")
        return context

    return authorize


async def check_catalog_membership(session: AsyncSession, context: AuthContext) -> None:
    # The UoW can wait on another tenant writer. Recheck before inserting into the catalog.
    roles = await session.scalar(
        select(Membership.roles)
        .join(User, User.id == Membership.user_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == context.tenant_id,
            Membership.user_id == uuid.UUID(context.actor_id),
            Membership.active.is_(True),
            User.active.is_(True),
            Tenant.active.is_(True),
        )
        .with_for_update()
    )
    if not roles or IOS_INVOICE_WRITER_ROLES.isdisjoint(roles):
        raise HTTPException(403, "Catalog creation permission is no longer active")

"""Transaction-time authorization for individual native collection actions."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.ios_catalog_access import check_native_membership
from app.core.ios_permissions import IOS_CLIENT_ID, IOS_COLLECTION_WRITER_ROLES
from app.models.platform import Tenant


async def check_collection_membership(session: AsyncSession, context: AuthContext) -> None:
    if context.client_id != IOS_CLIENT_ID or context.actor_type != "USER":
        raise HTTPException(403, "La operación requiere un usuario de cobranza de la app.")
    await session.scalar(select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update())
    await check_native_membership(
        session, context, allowed=IOS_COLLECTION_WRITER_ROLES,
        denied="Tu permiso de cobranza en esta empresa ya no está activo.",
    )

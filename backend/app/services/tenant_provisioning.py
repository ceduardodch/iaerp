from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import AutomationSettings, Membership, Tenant, User
from app.services.unit_of_work import append_audit


@dataclass(frozen=True)
class TenantOwnerProvision:
    organization_id: str
    external_subject: str
    ruc: str
    tenant_name: str
    email: str
    display_name: str


async def provision_tenant_owner(
    session: AsyncSession,
    *,
    request: TenantOwnerProvision,
    actor_id: str,
    correlation_id: str,
) -> Tenant:
    """Create or reconcile one tenant and its already-created OIDC owner."""
    if len(request.ruc) != 13 or not request.ruc.isdecimal():
        raise HTTPException(status_code=422, detail="RUC must contain exactly 13 digits")

    tenant = await session.scalar(
        select(Tenant).where(
            or_(Tenant.organization_id == request.organization_id, Tenant.ruc == request.ruc)
        )
    )
    if tenant is None:
        tenant = Tenant(
            ruc=request.ruc,
            name=request.tenant_name,
            organization_id=request.organization_id,
            active=True,
        )
        session.add(tenant)
        await session.flush()
    elif tenant.organization_id != request.organization_id or tenant.ruc != request.ruc:
        raise HTTPException(
            status_code=409,
            detail="RUC or Keycloak organization is already assigned",
        )

    user = await session.scalar(
        select(User).where(
            or_(User.external_subject == request.external_subject, User.email == request.email)
        )
    )
    if user is None:
        user = User(
            external_subject=request.external_subject,
            email=request.email,
            display_name=request.display_name,
            active=True,
        )
        session.add(user)
        await session.flush()
    elif user.external_subject != request.external_subject or user.email != request.email:
        raise HTTPException(status_code=409, detail="OIDC subject or email is already assigned")

    membership = await session.scalar(
        select(Membership).where(Membership.tenant_id == tenant.id, Membership.user_id == user.id)
    )
    if membership is None:
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        session.add(membership)
    membership.roles = ["owner", "admin"]
    membership.active = True

    automation = await session.get(AutomationSettings, tenant.id)
    if automation is None:
        session.add(AutomationSettings(tenant_id=tenant.id))

    context = AuthContext(
        actor_id=actor_id,
        actor_type="SYSTEM_PROVISIONER",
        tenant_id=tenant.id,
        roles=frozenset({"platform_admin"}),
        scopes=frozenset(),
        token_id=correlation_id,
    )
    await append_audit(
        session,
        context=context,
        action="tenant.owner.provisioned",
        entity_type="tenant",
        entity_id=str(tenant.id),
        correlation_id=correlation_id,
        idempotency_key=f"tenant-owner:{request.organization_id}:{request.external_subject}",
        details={"organization_id": request.organization_id, "subject": request.external_subject},
    )
    await session.flush()
    return tenant

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.platform import AuditEvent, AutomationSettings, Membership, Tenant, User
from app.services.tenant_provisioning import TenantOwnerProvision, provision_tenant_owner


def request(**overrides: str) -> TenantOwnerProvision:
    values = {
        "organization_id": "keycloak-btob",
        "external_subject": "keycloak-carlos",
        "ruc": "1793113192001",
        "tenant_name": "BTOB SAS",
        "email": "carlos.diaz@b2b.com.ec",
        "display_name": "Carlos Diaz",
    }
    values.update(overrides)
    return TenantOwnerProvision(**values)


async def test_provision_tenant_owner_is_idempotent_and_audited() -> None:
    async with SessionFactory.begin() as session:
        tenant = await provision_tenant_owner(
            session,
            request=request(),
            actor_id="operator-1",
            correlation_id=str(uuid.uuid4()),
        )
        repeated = await provision_tenant_owner(
            session,
            request=request(),
            actor_id="operator-1",
            correlation_id=str(uuid.uuid4()),
        )
        assert repeated.id == tenant.id

    async with SessionFactory() as session:
        stored_tenant = await session.scalar(select(Tenant).where(Tenant.ruc == "1793113192001"))
        assert stored_tenant is not None
        user = await session.scalar(select(User).where(User.external_subject == "keycloak-carlos"))
        assert user is not None
        membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == stored_tenant.id,
                Membership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.roles == ["owner", "admin"]
        assert await session.get(AutomationSettings, stored_tenant.id) is not None
        assert await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.tenant_id == stored_tenant.id)
        ) == 2


async def test_provision_rejects_conflicting_keycloak_identity() -> None:
    async with SessionFactory.begin() as session:
        await provision_tenant_owner(
            session,
            request=request(),
            actor_id="operator-1",
            correlation_id=str(uuid.uuid4()),
        )

    async with SessionFactory.begin() as session:
        with pytest.raises(HTTPException, match="already assigned"):
            await provision_tenant_owner(
                session,
                request=request(external_subject="different-subject"),
                actor_id="operator-1",
                correlation_id=str(uuid.uuid4()),
            )

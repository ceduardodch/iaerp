import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.auth import resolve_auth_context
from app.db.session import SessionFactory
from app.models.platform import ServiceAccount

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


async def test_service_account_resolves_tenant_and_intersects_scopes():
    async with SessionFactory() as session, session.begin():
        account = ServiceAccount(
            tenant_id=TENANT_A,
            client_id="agent-test",
            name="Agent Test",
            scopes=["context:read", "parties:read"],
            secret_hash="not-used-by-resource-server",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(account)

    async with SessionFactory() as session:
        context = await resolve_auth_context(
            {
                "sub": "service-account-agent-test",
                "client_id": "agent-test",
                "scope": "context:read parties:read products:write",
                "jti": "service-token-1",
            },
            session,
        )

    assert context.tenant_id == TENANT_A
    assert context.actor_type == "SERVICE_ACCOUNT"
    assert context.scopes == frozenset({"context:read", "parties:read"})


@pytest.mark.parametrize("active,expired", [(False, False), (True, True)])
async def test_revoked_or_expired_service_account_is_rejected(active: bool, expired: bool):
    async with SessionFactory() as session, session.begin():
        session.add(
            ServiceAccount(
                tenant_id=TENANT_A,
                client_id="agent-revoked",
                name="Agent Revoked",
                scopes=["context:read"],
                secret_hash="not-used-by-resource-server",
                active=active,
                expires_at=datetime.now(UTC)
                + (timedelta(hours=-1) if expired else timedelta(hours=1)),
            )
        )

    async with SessionFactory() as session:
        with pytest.raises(HTTPException) as exc:
            await resolve_auth_context(
                {
                    "sub": "service-account-agent-revoked",
                    "client_id": "agent-revoked",
                    "scope": "context:read",
                },
                session,
            )

    assert exc.value.status_code == 404


async def test_user_token_with_multiple_organizations_is_rejected(monkeypatch):
    from app.core import auth

    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    async with SessionFactory() as session:
        with pytest.raises(HTTPException) as exc:
            await resolve_auth_context(
                {
                    "sub": "user-a",
                    "organization": {
                        "tenant-a": {"id": "tenant-a"},
                        "tenant-b": {"id": "tenant-b"},
                    },
                    "scope": "context:read",
                },
                session,
            )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Token must contain exactly one organization"

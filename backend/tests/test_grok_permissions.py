"""Synthetic tenant memberships and signed tokens for the Grok connector."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import auth
from app.core.grok_permissions import GROK_CLIENT_ID
from app.db.session import SessionFactory
from app.mcp.server import IAERPTokenVerifier
from app.models.platform import ServiceAccount
from tests.conftest import TENANT_A, TENANT_B
from tests.test_ios_permissions import claims, membership, oidc_signer

READ = {"context:read", "invoices:read", "parties:read", "products:read", "receivables:read"}
PROTOCOL = {"openid", "organization", "offline_access"}
BILLING = {"invoices:write", "invoices:issue", "invoices:email"}
COLLECTIONS = {"receivables:write"}
SCOPES = " ".join(READ | PROTOCOL | BILLING | COLLECTIONS | {"credit-notes:issue", "roles:write"})


def grok_claims(alias="tenant-a", **overrides):
    payload = claims(alias, azp=GROK_CLIENT_ID, aud=auth.settings.OIDC_MCP_AUDIENCE, scope=SCOPES)
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "role,expected",
    [
        ("owner", BILLING | COLLECTIONS),
        ("admin", BILLING | COLLECTIONS),
        ("billing", BILLING),
        ("collections", COLLECTIONS),
        ("viewer", set()),
        ("unknown", set()),
    ],
)
async def test_grok_uses_current_company_role_and_only_approved_scopes(monkeypatch, role, expected):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    await membership(TENANT_A, [role])
    await membership(TENANT_B, ["viewer"])
    async with SessionFactory() as session:
        context = await auth.resolve_auth_context(grok_claims(), session)
        assert context.tenant_id == TENANT_A
        assert context.scopes == READ | PROTOCOL | expected
        other = await auth.resolve_auth_context(grok_claims("tenant-b"), session)
        assert other.tenant_id == TENANT_B
        assert other.scopes == READ | PROTOCOL
        limited = await auth.resolve_auth_context(grok_claims(scope="context:read"), session)
        assert limited.scopes == {"context:read"}


async def test_grok_user_keeps_company_binding_after_service_account_collision(monkeypatch):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    async with SessionFactory() as session, session.begin():
        session.add(
            ServiceAccount(
                tenant_id=TENANT_B,
                client_id=GROK_CLIENT_ID,
                name="Synthetic collision",
                secret_hash=uuid4().hex,
                scopes=["invoices:issue"],
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    async with SessionFactory() as session:
        context = await auth.resolve_auth_context(grok_claims(), session)
        assert (context.actor_type, context.tenant_id) == ("USER", TENANT_A)
        with pytest.raises(HTTPException) as mismatch:
            await auth.resolve_auth_context(grok_claims(client_id="other"), session)
        assert mismatch.value.status_code == 403
        with pytest.raises(HTTPException) as no_member:
            await auth.resolve_auth_context(grok_claims("tenant-b"), session)
        assert no_member.value.status_code == 404
        with pytest.raises(HTTPException) as ambiguous:
            await auth.resolve_auth_context(
                grok_claims(organization={"a": {"id": "tenant-a"}, "b": {"id": "tenant-b"}}),
                session,
            )
        assert ambiguous.value.status_code == 403


async def test_grok_token_is_accepted_on_mcp_and_rejected_on_rest_even_if_dual_audience(
    client,
    monkeypatch,
):
    sign = oidc_signer(monkeypatch)
    token = sign(
        grok_claims(aud=[auth.settings.OIDC_API_AUDIENCE, auth.settings.OIDC_MCP_AUDIENCE])
    )
    assert await IAERPTokenVerifier().verify_token(token) is not None
    response = await client.get("/api/v1/context", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Grok connector requires the MCP endpoint"

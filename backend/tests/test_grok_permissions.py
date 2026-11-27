"""Synthetic tenant memberships and signed tokens for the Grok connector."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core import auth
from app.core.config import Settings
from app.core.grok_permissions import (
    GROK_BUSINESS_ANALYSIS_SCOPE,
    GROK_CLIENT_ID,
    GROK_TAX_SUMMARY_SCOPE,
)
from app.db.session import SessionFactory
from app.mcp.server import TOOL_REQUIRED_SCOPES, IAERPTokenVerifier
from app.models.platform import ServiceAccount
from tests.conftest import TENANT_A, TENANT_B
from tests.test_ios_permissions import claims, membership, oidc_signer
from tests.test_mcp_receivables import mcp_lifespan, mcp_session

READ = {"context:read", "invoices:read", "parties:read", "products:read", "receivables:read"}
PROTOCOL = {"openid", "organization", "offline_access"}
BILLING = {"invoices:write", "invoices:issue", "invoices:email"}
COLLECTIONS = {"receivables:write"}
TAX_READ = {"tax:read"}
SCOPES = " ".join(
    READ | PROTOCOL | BILLING | COLLECTIONS | TAX_READ
    | {"tax:write", "credit-notes:issue", "roles:write"}
)


def grok_claims(alias="tenant-a", **overrides):
    payload = claims(alias, azp=GROK_CLIENT_ID, aud=auth.settings.OIDC_MCP_AUDIENCE, scope=SCOPES)
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "role,expected",
    [
        ("owner", BILLING | COLLECTIONS | TAX_READ),
        ("admin", BILLING | COLLECTIONS | TAX_READ),
        ("accountant", TAX_READ),
        ("auditor", TAX_READ),
        ("billing", BILLING),
        ("collections", COLLECTIONS),
        ("viewer", set()),
        ("unknown", set()),
    ],
)
async def test_grok_uses_current_company_role_and_only_approved_scopes(monkeypatch, role, expected):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_A}))
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


async def test_grok_tax_read_requires_the_opted_in_company_not_a_token_label(monkeypatch):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_A}))
    await membership(TENANT_A, ["owner"])
    await membership(TENANT_B, ["owner"])
    async with SessionFactory() as session:
        other = await auth.resolve_auth_context(
            grok_claims(organization={"tenant-a": {"id": "tenant-b"}}, ruc="1799999999001"),
            session,
        )
        assert other.tenant_id == TENANT_B
        assert "tax:read" not in other.scopes
        monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset())
        disabled = await auth.resolve_auth_context(grok_claims(), session)
        assert "tax:read" not in disabled.scopes


@pytest.mark.parametrize(
    "grant,expected",
    [
        (GROK_TAX_SUMMARY_SCOPE, True),
        ("tax:read", True),
        (f"{GROK_TAX_SUMMARY_SCOPE} tax:read", True),
        ("tax:write", False),
        ("receivables:read", False),
        ("", False),
    ],
)
async def test_desktop_fiscal_grant_requires_company_and_role(monkeypatch, grant, expected):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_A}))
    await membership(TENANT_A, ["accountant"])
    await membership(TENANT_B, ["accountant"])
    async with SessionFactory() as session:
        for alias, is_opted_in in (("tenant-a", True), ("tenant-b", False)):
            context = await auth.resolve_auth_context(grok_claims(alias, scope=grant), session)
            assert ("tax:read" in context.scopes) is (is_opted_in and expected)
            assert "tax:write" not in context.scopes
    await membership(TENANT_A, ["billing"])
    async with SessionFactory() as session:
        restricted = await auth.resolve_auth_context(grok_claims(scope=grant), session)
        assert "tax:read" not in restricted.scopes


@pytest.mark.parametrize(
    "role,grant,allowed",
    [
        ("owner", GROK_BUSINESS_ANALYSIS_SCOPE, True),
        ("admin", GROK_BUSINESS_ANALYSIS_SCOPE, True),
        ("accountant", GROK_BUSINESS_ANALYSIS_SCOPE, False),
        ("auditor", GROK_BUSINESS_ANALYSIS_SCOPE, False),
        ("viewer", GROK_BUSINESS_ANALYSIS_SCOPE, False),
        ("owner", "context:read tax:read", False),
        ("owner", GROK_TAX_SUMMARY_SCOPE, False),
        ("owner", "reports:read", False),
    ],
)
async def test_grok_business_report_requires_its_own_grant_company_and_role(
    monkeypatch, role, grant, allowed
):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "oidc")
    monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_A}))
    await membership(TENANT_A, [role])
    await membership(TENANT_B, [role])
    async with SessionFactory() as session:
        enabled = await auth.resolve_auth_context(grok_claims(scope=grant), session)
        other = await auth.resolve_auth_context(
            grok_claims(organization={"tenant-a": {"id": "tenant-b"}}, scope=grant),
            session,
        )
        assert ("reports:read" in enabled.scopes) is allowed
        assert "reports:read" not in other.scopes
        assert ("tax:read" in enabled.scopes) is (
            role == "owner" and grant in (GROK_TAX_SUMMARY_SCOPE, "context:read tax:read")
        )
        assert not any(scope.endswith(":write") for scope in enabled.scopes)
        monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset())
        disabled = await auth.resolve_auth_context(grok_claims(scope=grant), session)
        assert "reports:read" not in disabled.scopes


def test_config_parses_company_ids_and_rejects_invalid_values(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("GROK_ANALYSIS_TENANT_IDS", f"{TENANT_A}, {TENANT_B}, {TENANT_A}")
    assert Settings().GROK_ANALYSIS_TENANT_IDS == {TENANT_A, TENANT_B}
    monkeypatch.setenv("GROK_ANALYSIS_TENANT_IDS", "")
    assert not Settings().GROK_ANALYSIS_TENANT_IDS
    monkeypatch.setenv("GROK_ANALYSIS_TENANT_IDS", "*")
    with pytest.raises(ValidationError):
        Settings()


async def test_grok_catalog_uses_signed_grants_and_current_company_membership(monkeypatch):
    sign = oidc_signer(monkeypatch)
    monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_A, TENANT_B}))
    await membership(TENANT_A, ["owner"])
    await membership(TENANT_B, ["auditor"])
    requested = f"context:read {GROK_TAX_SUMMARY_SCOPE} {GROK_BUSINESS_ANALYSIS_SCOPE}"
    async with mcp_lifespan():
        for alias, reports_allowed in (("tenant-a", True), ("tenant-b", False)):
            token = sign(grok_claims(alias, scope=requested))
            async with mcp_session(token) as mcp:
                names = {tool.name for tool in (await mcp.list_tools()).tools}
                expected = {"context.get", "tax.get_period_summary"}
                if reports_allowed:
                    expected.add("erp.read_report")
                assert names == expected
        monkeypatch.setattr(auth.settings, "GROK_ANALYSIS_TENANT_IDS", frozenset({TENANT_B}))
        async with mcp_session(sign(grok_claims(scope=requested))) as disabled:
            assert {tool.name for tool in (await disabled.list_tools()).tools} == {"context.get"}


def test_grok_fiscal_grant_only_opens_the_summary():
    # The connector is MCP-only. Review its delegated scope boundary explicitly
    # before introducing another MCP tool backed by the general tax:read grant.
    assert {name for name, scope in TOOL_REQUIRED_SCOPES.items() if scope == "tax:read"} == {
        "tax.get_period_summary"
    }


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

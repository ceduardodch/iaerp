"""Contrato MCP del CRM: permisos, tenant, politica e idempotencia."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionFactory, engine
from app.mcp import server as mcp_server
from app.mcp.tool_fingerprints import EXPECTED_TOOL_FINGERPRINTS
from app.models.crm import Lead, LeadActivity
from app.models.platform import AutomationRateWindow, AutomationSettings, ServiceAccount
from app.services import crm, crm_integrations
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for
from tests.test_mcp_receivables import (
    _enable_automation_writes,
    mcp_lifespan,
    mcp_session,
)


def _lead_payload(number: str, *, name: str = "Prospecto MCP") -> dict[str, object]:
    return {
        "partyName": name,
        "partyIdentificationType": "RUC",
        "partyIdentificationNumber": number,
        "partyEmail": "prospecto@example.com",
        "title": "Revision de costos AWS",
    }


async def test_mcp_crm_catalog_is_filtered_by_scope(client) -> None:
    without_crm = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    with_crm = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write"],
    )

    async with mcp_lifespan():
        async with mcp_session(without_crm) as session:
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert not any(name.startswith("leads.") for name in names)

        async with mcp_session(with_crm) as session:
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert {
                "leads.list",
                "leads.activities",
                "leads.create_with_party",
                "leads.create_activity",
            }.issubset(names)


async def test_mcp_crm_write_requires_policy_and_is_idempotent(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "automation:write"],
    )
    arguments = {
        "lead": _lead_payload("1793000001001"),
        "idempotencyKey": "mcp-lead-create-0001",
    }

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            blocked = await session.call_tool("leads.create_with_party", arguments)
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, token, "mcp-crm-enable-0001")

        async with mcp_session(token) as session:
            created = await session.call_tool("leads.create_with_party", arguments)
            repeated = await session.call_tool("leads.create_with_party", arguments)
            assert created.isError is False, created.content
            assert repeated.isError is False, repeated.content
            assert repeated.structuredContent["id"] == created.structuredContent["id"]

            listed = await session.call_tool("leads.list", {"status": "NEW"})
            assert listed.isError is False, listed.content
            assert created.structuredContent["id"] in {
                item["id"] for item in listed.structuredContent["result"]
            }

    rest = await client.get(
        f"/api/v1/crm/leads/{created.structuredContent['id']}",
        headers=auth(token),
    )
    assert rest.status_code == 200, rest.text
    assert rest.json()["party"]["name"] == "Prospecto MCP"

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count()).select_from(Lead).where(Lead.tenant_id == TENANT_A)
        )
    assert count == 1


async def test_mcp_crm_activity_is_tenant_scoped_and_idempotent(client) -> None:
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "automation:write"],
    )
    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["leads:write", "automation:write"],
    )
    await _enable_automation_writes(client, token_a, "mcp-crm-enable-a-0001")
    await _enable_automation_writes(client, token_b, "mcp-crm-enable-b-0001")

    async with mcp_lifespan():
        async with mcp_session(token_a) as session:
            lead = await session.call_tool(
                "leads.create_with_party",
                {
                    "lead": _lead_payload("1793000002001", name="Empresa A"),
                    "idempotencyKey": "mcp-lead-create-a-0001",
                },
            )
            assert lead.isError is False, lead.content
            activity_arguments = {
                "activity": {
                    "leadId": lead.structuredContent["id"],
                    "activityType": "TASK",
                    "subject": "Llamar al responsable",
                    "outcome": "PENDING",
                    "reminderDate": "2026-08-10T14:00:00-05:00",
                },
                "idempotencyKey": "mcp-lead-activity-0001",
            }
            activity = await session.call_tool("leads.create_activity", activity_arguments)
            repeated = await session.call_tool("leads.create_activity", activity_arguments)
            assert activity.isError is False, activity.content
            assert repeated.structuredContent["id"] == activity.structuredContent["id"]
            activities = await session.call_tool(
                "leads.activities",
                {"leadId": lead.structuredContent["id"]},
            )
            assert activities.isError is False, activities.content
            assert [item["id"] for item in activities.structuredContent["result"]] == [
                activity.structuredContent["id"]
            ]

        async with mcp_session(token_b) as session:
            foreign = await session.call_tool(
                "leads.create_activity",
                {
                    "activity": {
                        "leadId": lead.structuredContent["id"],
                        "activityType": "NOTE",
                        "subject": "No debe cruzar tenant",
                    },
                    "idempotencyKey": "mcp-lead-foreign-0001",
                },
            )
            assert foreign.isError is True
            assert "Lead not found" in foreign.content[0].text

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(LeadActivity)
            .where(LeadActivity.tenant_id == TENANT_A)
        )
    assert count == 1


async def test_mcp_crm_rejects_extra_source_naive_time_and_changed_replay(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:write", "automation:write"],
    )
    await _enable_automation_writes(client, token, "mcp-crm-enable-validation")

    async with mcp_lifespan(), mcp_session(token) as session:
        spoofed = await session.call_tool(
            "leads.create_with_party",
            {
                "lead": {**_lead_payload("1793000003001"), "source": "META_LEAD_AD"},
                "idempotencyKey": "mcp-lead-source-spoof",
            },
        )
        assert spoofed.isError is True
        assert "extra_forbidden" in spoofed.content[0].text

        created = await session.call_tool(
            "leads.create_with_party",
            {
                "lead": _lead_payload("1793000003002"),
                "idempotencyKey": "mcp-lead-validation-create",
            },
        )
        assert created.isError is False, created.content
        assert created.structuredContent["status"] == "NEW"
        assert created.structuredContent["source"] == "MCP"

        naive = await session.call_tool(
            "leads.create_activity",
            {
                "activity": {
                    "leadId": created.structuredContent["id"],
                    "activityType": "TASK",
                    "subject": "Fecha sin zona",
                    "reminderDate": "2026-08-10T14:00:00",
                },
                "idempotencyKey": "mcp-lead-naive-reminder",
            },
        )
        assert naive.isError is True
        assert "must include a timezone" in naive.content[0].text

        replay_key = "mcp-lead-changed-replay"
        first = await session.call_tool(
            "leads.create_activity",
            {
                "activity": {
                    "leadId": created.structuredContent["id"],
                    "activityType": "NOTE",
                    "subject": "Primer valor",
                },
                "idempotencyKey": replay_key,
            },
        )
        changed = await session.call_tool(
            "leads.create_activity",
            {
                "activity": {
                    "leadId": created.structuredContent["id"],
                    "activityType": "NOTE",
                    "subject": "Otro valor",
                },
                "idempotencyKey": replay_key,
            },
        )
        assert first.isError is False, first.content
        assert changed.isError is True
        assert "different request" in changed.content[0].text


async def test_mcp_rate_limit_is_durable_and_counts_rejected_attempt(client, monkeypatch) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["leads:read"])
    monkeypatch.setattr(mcp_server, "MCP_TOOL_RATE_LIMIT_PER_MINUTE", 2)

    async with mcp_lifespan(), mcp_session(token) as session:
        assert (await session.call_tool("leads.list", {})).isError is False
        assert (await session.call_tool("leads.list", {})).isError is False
        rejected = await session.call_tool("leads.list", {})
        assert rejected.isError is True
        assert "Rate limit exceeded" in rejected.content[0].text

    async with SessionFactory() as session:
        window = await session.scalar(
            select(AutomationRateWindow).where(
                AutomationRateWindow.tenant_id == TENANT_A,
                AutomationRateWindow.tool_name == "leads.list",
            )
        )
    assert window is not None
    assert window.attempt_count == 3


async def test_changed_tool_fingerprint_suspends_tool(client, monkeypatch) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["leads:read"])
    monkeypatch.setitem(EXPECTED_TOOL_FINGERPRINTS, "leads.list", "changed")

    async with mcp_lifespan(), mcp_session(token) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        direct_call = await session.call_tool("leads.list", {})
    assert "leads.list" not in names
    assert "leads.activities" in names
    assert direct_call.isError is True
    assert "fingerprint mismatch" in direct_call.content[0].text


async def test_rest_service_account_cannot_bypass_automation_policy(client, monkeypatch) -> None:
    settings = get_settings()
    client_id = "iaerp-test-crm-agent"
    account_id = uuid.uuid4()
    async with SessionFactory() as session, session.begin():
        session.add(
            ServiceAccount(
                id=account_id,
                tenant_id=TENANT_A,
                client_id=client_id,
                name="CRM test agent",
                scopes=["leads:write"],
                secret_hash="not-used-in-this-test",  # pragma: allowlist secret
                active=True,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    token = jwt.encode(
        {
            "iss": "iaerp-dev",
            "aud": [settings.OIDC_API_AUDIENCE],
            "azp": client_id,
            "sub": f"service-account-{client_id}",
            "scope": "leads:write",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": "service-account-crm-policy-test",
        },
        settings.DEV_JWT_SECRET,
        algorithm="HS256",
    )

    spoofed_capture = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "rest-service-account-spoofed-capture"),
        json={
            "source": "META_LEAD_AD",
            "sourceExternalId": "fake-meta-lead",
            "partyName": "Fake Meta Lead",
            "partyEmail": "fake-meta@example.com",
            "title": "Fake campaign attribution",
            "consentCapturedAt": datetime.now(UTC).isoformat(),
            "consentTextVersion": "fake",
        },
    )
    assert spoofed_capture.status_code == 403

    response = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "rest-service-account-lead"),
        json=_lead_payload("1793000004001"),
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Automation writes are disabled for this tenant"

    async with SessionFactory() as session, session.begin():
        automation = await session.get(AutomationSettings, TENANT_A)
        assert automation is not None
        automation.writes_enabled = True
    allowed = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "rest-service-account-normalized"),
        json={
            **_lead_payload("1793000004002"),
            "status": "WON",
            "source": "META_LEAD_AD",
            "score": 100,
            "hotness": "HOT",
            "estimatedValue": "999999.99",
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["status"] == "NEW"
    assert allowed.json()["source"] == "MCP"
    assert allowed.json()["score"] == 0
    assert allowed.json()["hotness"] == "COLD"
    assert allowed.json()["estimatedValue"] is None

    lead_id = allowed.json()["id"]
    async with SessionFactory() as session, session.begin():
        account = await session.get(ServiceAccount, account_id)
        automation = await session.get(AutomationSettings, TENANT_A)
        assert account is not None and automation is not None
        account.scopes = ["leads:write", "communications:write"]
        automation.writes_enabled = False
    legacy_token = jwt.encode(
        {
            "iss": "iaerp-dev",
            "aud": [settings.OIDC_API_AUDIENCE],
            "azp": client_id,
            "sub": f"service-account-{client_id}",
            "scope": "communications:write",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": "legacy-service-account-message-test",
        },
        settings.DEV_JWT_SECRET,
        algorithm="HS256",
    )
    provider_calls: list[str] = []

    async def fake_send_google_email(*_args, **_kwargs) -> None:
        provider_calls.append("email")

    monkeypatch.setattr(crm_integrations, "send_google_email", fake_send_google_email)
    forbidden_message = await client.post(
        f"/api/v1/crm/leads/{lead_id}/messages",
        headers=auth(legacy_token, "legacy-service-account-message"),
        json={
            "channel": "EMAIL",
            "subject": "Must not send",
            "message": "Blocked before provider call",
        },
    )
    assert forbidden_message.status_code == 403, forbidden_message.text
    assert provider_calls == []
    async with SessionFactory() as session, session.begin():
        automation = await session.get(AutomationSettings, TENANT_A)
        assert automation is not None
        automation.writes_enabled = True

    naive_activity = await client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        headers=auth(token, "rest-service-account-naive-reminder"),
        json={
            "leadId": lead_id,
            "activityType": "TASK",
            "subject": "Naive reminder",
            "reminderDate": "2026-08-10T09:00:00",
        },
    )
    assert naive_activity.status_code == 422
    assert naive_activity.json()["detail"] == "reminder_date must include a timezone"

    monkeypatch.setattr(crm, "AUTOMATION_WRITE_RATE_LIMIT_PER_MINUTE", 3)
    activity_payload = {
        "leadId": lead_id,
        "activityType": "TASK",
        "subject": "Rate-limited follow-up",
        "reminderDate": "2026-08-10T09:00:00-05:00",
    }
    first_activity = await client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        headers=auth(token, "rest-service-account-activity-rate-1"),
        json=activity_payload,
    )
    second_activity = await client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        headers=auth(token, "rest-service-account-activity-rate-2"),
        json={**activity_payload, "subject": "Second rate-limited follow-up"},
    )
    rate_limited_activity = await client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        headers=auth(token, "rest-service-account-activity-rate-3"),
        json={**activity_payload, "subject": "Rejected rate-limited follow-up"},
    )
    assert first_activity.status_code == 201, first_activity.text
    assert second_activity.status_code == 201, second_activity.text
    assert rate_limited_activity.status_code == 429, rate_limited_activity.text
    monkeypatch.setattr(crm, "AUTOMATION_WRITE_RATE_LIMIT_PER_MINUTE", 120)

    forbidden_operations = [
        (
            f"/api/v1/crm/leads/{lead_id}",
            "rest-service-account-update",
            {"title": "Changed by agent"},
        ),
        (
            f"/api/v1/crm/leads/{lead_id}/status",
            "rest-service-account-status",
            {"newStatus": "WON"},
        ),
        (
            f"/api/v1/crm/leads/{lead_id}/qualification",
            "rest-service-account-qualification",
            {"status": "DISQUALIFIED", "reason": "Agent decision"},
        ),
        (
            f"/api/v1/crm/leads/{lead_id}/activities/{uuid.uuid4()}/reminder",
            "rest-service-account-reminder",
            {"completed": True},
        ),
    ]
    for path, key, payload in forbidden_operations:
        forbidden = await client.put(path, headers=auth(token, key), json=payload)
        assert forbidden.status_code == 403, forbidden.text
        assert forbidden.json()["detail"] == (
            "Service accounts may only create leads and activities"
        )


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row locks are required for this deadlock contract",
)
async def test_rest_service_account_rate_preflight_does_not_deadlock(client) -> None:
    settings = get_settings()
    client_id = "iaerp-test-crm-rate-preflight"
    async with SessionFactory() as session, session.begin():
        session.add(
            ServiceAccount(
                tenant_id=TENANT_A,
                client_id=client_id,
                name="CRM rate preflight test",
                scopes=["leads:write"],
                secret_hash="not-used-in-this-test",  # pragma: allowlist secret
                active=True,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        automation = await session.get(AutomationSettings, TENANT_A)
        assert automation is not None
        automation.writes_enabled = True
    token = jwt.encode(
        {
            "iss": "iaerp-dev",
            "aud": [settings.OIDC_API_AUDIENCE],
            "azp": client_id,
            "sub": f"service-account-{client_id}",
            "scope": "leads:write",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "jti": "service-account-rate-preflight-test",
        },
        settings.DEV_JWT_SECRET,
        algorithm="HS256",
    )
    async with asyncio.timeout(5):
        response = await client.post(
            "/api/v1/crm/leads/with-party",
            headers=auth(token, "rest-service-account-no-deadlock"),
            json=_lead_payload("1793000004999"),
        )
    assert response.status_code == 201, response.text

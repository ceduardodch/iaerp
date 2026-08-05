import asyncio
import hashlib
import hmac
import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory, engine
from app.models.crm import MetaAdsIntegration, SocialCampaign, SocialCampaignVariant
from app.models.platform import Membership, OutboxEvent
from app.services import social_campaigns
from app.workers.campaigns import (
    CONSUMER_NAME,
    handle_campaign_activation,
    handle_campaign_pause,
    handle_campaign_policy,
    handle_campaign_preparation,
)
from app.workers.outbox import OutboxMessage, consume_once

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


async def token_for(
    client,
    scopes: list[str],
    *,
    tenant_id: uuid.UUID = TENANT_A,
    email: str = "a@iaerp.local",
) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, object]:
        return self._payload


class FakeMetaClient:
    posts: list[tuple[str, dict[str, object]]] = []
    creative_count = 0
    ad_count = 0
    fail_active_object_id: str | None = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url: str, **kwargs):
        data = kwargs.get("data") or {}
        self.posts.append((url, data))
        if (
            data.get("status") == "ACTIVE"
            and self.fail_active_object_id
            and url.endswith(f"/{self.fail_active_object_id}")
        ):
            return FakeResponse({"error": {"message": "activation rejected"}}, 400)
        if url.endswith("/adimages"):
            return FakeResponse({"images": {"campaign.jpg": {"hash": "image-hash-1"}}})
        if url.endswith("/campaigns"):
            return FakeResponse({"id": "meta-campaign-1"})
        if url.endswith("/adsets"):
            return FakeResponse({"id": "meta-adset-1"})
        if url.endswith("/adcreatives"):
            self.__class__.creative_count += 1
            return FakeResponse({"id": f"meta-creative-{self.creative_count}"})
        if url.endswith("/ads"):
            self.__class__.ad_count += 1
            return FakeResponse({"id": f"meta-ad-{self.ad_count}"})
        return FakeResponse({"success": True})

    async def get(self, url: str, **kwargs):
        if url.endswith("/act_123456"):
            return FakeResponse(
                {"id": "act_123456", "currency": "USD", "timezone_name": "America/Guayaquil"}
            )
        if url.endswith("/lead-response-1"):
            return FakeResponse(
                {
                    "id": "lead-response-1",
                    "created_time": "2026-08-04T15:30:00+0000",
                    "form_id": "instant-form-1",
                    "ad_id": "meta-ad-1",
                    "field_data": [
                        {"name": "full_name", "values": ["Ana Campaña"]},
                        {"name": "email", "values": ["ana.campana@example.com"]},
                        {"name": "phone_number", "values": ["+593999000222"]},
                        {"name": "company_name", "values": ["Empresa AWS"]},
                        {"name": "job_title", "values": ["CTO"]},
                        {"name": "uses_aws", "values": ["Sí"]},
                        {"name": "decision_authority", "values": ["Sí"]},
                    ],
                }
            )
        if url.endswith("/meta-ad-1"):
            return FakeResponse(
                {
                    "id": "meta-ad-1",
                    "name": "Anuncio IAERP",
                    "campaign": {"id": "meta-campaign-1", "name": "Campaña IAERP"},
                }
            )
        if url.endswith("/meta-ad-1/insights"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "date_start": "2026-08-04",
                            "date_stop": "2026-08-04",
                            "spend": "4.00",
                            "impressions": "1000",
                            "clicks": "20",
                            "actions": [
                                {"action_type": "onsite_conversion.lead_grouped", "value": "2"}
                            ],
                        }
                    ]
                }
            )
        if url.endswith("/meta-ad-2/insights"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "date_start": "2026-08-04",
                            "date_stop": "2026-08-04",
                            "spend": "6.00",
                            "impressions": "1200",
                            "clicks": "12",
                            "actions": [{"action_type": "lead", "value": "1"}],
                        }
                    ]
                }
            )
        if kwargs.get("params", {}).get("fields") == "id,name":
            return FakeResponse({"data": []})
        return FakeResponse({}, 404)


async def test_campaign_writes_and_spending_policy_require_permission_and_owner(client):
    read_token = await token_for(client, ["communications:read"])
    assert (await client.get("/api/v1/crm/campaigns", headers=auth(read_token))).status_code == 200
    forbidden_create = await client.post(
        "/api/v1/crm/campaigns",
        headers=auth(read_token, "meta-campaign-readonly-create-0001"),
        json={
            "name": "No permitida",
            "dailyBudget": "5.00",
            "primaryText": "Texto",
            "headline": "Titular",
        },
    )
    assert forbidden_create.status_code == 403

    async with SessionFactory() as session, session.begin():
        membership = await session.scalar(
            select(Membership).where(Membership.tenant_id == TENANT_A)
        )
        assert membership is not None
        membership.roles = ["sales"]
    write_token = await token_for(client, ["communications:read", "communications:write"])
    forbidden_policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(write_token, "meta-campaign-policy-nonowner-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "10.00"},
    )
    assert forbidden_policy.status_code == 403


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="PostgreSQL row locks are required for this concurrency contract",
)
async def test_concurrent_campaign_activations_cannot_exceed_tenant_budget(client):
    token = await token_for(
        client,
        ["communications:read", "communications:write"],
    )
    connection = await client.put(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-concurrent-integration-0001"),
        json={
            "adAccountId": "act_concurrent",
            "pageId": "page-concurrent",
            "defaultLeadFormId": "form-concurrent",
            "accessToken": "meta-access-token-for-concurrency-tests",
            "appSecret": "app-secret-for-concurrency-tests",  # pragma: allowlist secret
            "verifyToken": "verify-token-for-concurrency-tests",
        },
    )
    assert connection.status_code == 200, connection.text
    policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-concurrent-policy-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "10.00"},
    )
    assert policy.status_code == 200, policy.text

    campaign_ids: list[uuid.UUID] = []
    async with SessionFactory() as session, session.begin():
        for index in range(2):
            campaign = SocialCampaign(
                tenant_id=TENANT_A,
                name=f"Concurrent campaign {index}",
                status="PREPARED",
                daily_budget=Decimal("6.00"),
                primary_text="Concurrent budget test",
                headline="Concurrent test",
                external_campaign_id=f"meta-campaign-concurrent-{index}",
                external_adset_id=f"meta-adset-concurrent-{index}",
                external_ad_id=f"meta-ad-concurrent-{index}",
            )
            session.add(campaign)
            await session.flush()
            session.add(
                SocialCampaignVariant(
                    tenant_id=TENANT_A,
                    campaign_id=campaign.id,
                    key="principal",
                    name="Principal",
                    position=1,
                    primary_text="Concurrent budget test",
                    headline="Concurrent test",
                    external_creative_id=f"meta-creative-concurrent-{index}",
                    external_ad_id=f"meta-ad-concurrent-{index}",
                )
            )
            campaign_ids.append(campaign.id)

    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/crm/campaigns/{campaign_id}/activate",
                headers=auth(token, f"meta-concurrent-activate-{index:04d}"),
                json={"confirmed": True},
            )
            for index, campaign_id in enumerate(campaign_ids)
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 422]


async def test_meta_campaign_is_prepared_paused_and_requires_confirmed_activation(
    client, monkeypatch
):
    FakeMetaClient.posts = []
    FakeMetaClient.creative_count = 0
    FakeMetaClient.ad_count = 0
    FakeMetaClient.fail_active_object_id = None
    stored: dict[str, bytes] = {}

    async def upload(*, object_key: str, data: bytes, **_kwargs):
        stored[object_key] = data
        return object()

    async def download(*, object_key: str, **_kwargs):
        return stored[object_key]

    monkeypatch.setattr(social_campaigns.storage, "upload_private_object", upload)
    monkeypatch.setattr(social_campaigns.storage, "download_artifact", download)
    monkeypatch.setattr(social_campaigns.httpx, "AsyncClient", FakeMetaClient)
    monkeypatch.setattr(social_campaigns.settings, "PUBLIC_API_URL", "https://api.example/api/v1")
    token = await token_for(
        client,
        ["communications:read", "communications:write", "leads:read", "leads:write"],
    )

    connection = await client.put(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-save-0001"),
        json={
            "adAccountId": "123456",
            "pageId": "page-1",
            "instagramActorId": "ig-1",
            "defaultLeadFormId": "instant-form-1",
            "accessToken": "meta-access-token-for-tests-123",
            "appSecret": "app-secret-for-tests",  # pragma: allowlist secret
            "verifyToken": "verify-token-for-tests",
        },
    )
    assert connection.status_code == 200, connection.text
    assert connection.json() == {
        "connected": True,
        "adAccountId": "act_123456",
        "pageId": "page-1",
        "instagramActorId": "ig-1",
        "defaultLeadFormId": "instant-form-1",
        "accountCurrency": None,
        "accountTimezone": None,
        "webhookUrl": "https://api.example/api/v1/crm/webhooks/meta-leads",
    }
    async with SessionFactory() as session:
        integration = await session.scalar(select(MetaAdsIntegration))
        assert integration is not None
        assert integration.access_token_encrypted != "meta-access-token-for-tests-123"

    created = await client.post(
        "/api/v1/crm/campaigns",
        headers=auth(token, "meta-campaign-create-0001"),
        json={
            "name": "Campaña de demostración",
            "dailyBudget": "5.00",
            "ageMin": 25,
            "ageMax": 60,
            "countries": ["EC"],
            "primaryText": "Pide una demostración de IAERP.",
            "headline": "Ordena tu empresa",
            "description": "Te contactamos para una demo.",
        },
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["status"] == "DRAFT"

    tenant_b_token = await token_for(
        client,
        ["communications:read"],
        tenant_id=TENANT_B,
        email="b@iaerp.local",
    )
    tenant_b_campaigns = await client.get("/api/v1/crm/campaigns", headers=auth(tenant_b_token))
    assert tenant_b_campaigns.status_code == 200
    assert tenant_b_campaigns.json() == []
    tenant_b_integration = await client.get(
        "/api/v1/crm/integrations/meta-ads", headers=auth(tenant_b_token)
    )
    assert tenant_b_integration.status_code == 200
    assert tenant_b_integration.json()["connected"] is False
    assert (
        await client.get(
            f"/api/v1/crm/campaigns/{campaign['id']}/variants",
            headers=auth(tenant_b_token),
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/crm/campaigns/{campaign['id']}/insights",
            headers=auth(tenant_b_token),
        )
    ).status_code == 404
    tenant_b_write_token = await token_for(
        client,
        ["communications:read", "communications:write"],
        tenant_id=TENANT_B,
        email="b@iaerp.local",
    )
    foreign_write_cases = [
        (
            f"/api/v1/crm/campaigns/{campaign['id']}/prepare",
            "meta-tenant-b-prepare-0001",
            None,
        ),
        (
            f"/api/v1/crm/campaigns/{campaign['id']}/activate",
            "meta-tenant-b-activate-0001",
            {"confirmed": True},
        ),
        (
            f"/api/v1/crm/campaigns/{campaign['id']}/pause",
            "meta-tenant-b-pause-0001",
            None,
        ),
        (
            f"/api/v1/crm/campaigns/{campaign['id']}/insights/sync",
            "meta-tenant-b-insights-0001",
            {"days": 3},
        ),
    ]
    for path, key, body in foreign_write_cases:
        response = await client.post(
            path,
            headers=auth(tenant_b_write_token, key),
            json=body,
        )
        assert response.status_code == 404

    image = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/creative",
        headers=auth(token, "meta-campaign-image-0001"),
        files={"creative": ("campaign.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )
    assert image.status_code == 200, image.text
    assert image.json()["creativeSha256"]

    variants_before = await client.get(
        f"/api/v1/crm/campaigns/{campaign['id']}/variants", headers=auth(token)
    )
    assert variants_before.status_code == 200
    principal = variants_before.json()[0]
    assert principal["key"] == "principal"
    second = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/variants",
        headers=auth(token, "meta-campaign-variant-0001"),
        json={
            "key": "costo",
            "name": "Ángulo costo",
            "angle": "COST",
            "primaryText": "Reduce el costo de operar AWS.",
            "headline": "Controla tu costo AWS",
            "description": "Revisión inicial sin costo.",
        },
    )
    assert second.status_code == 201, second.text
    second_image = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/variants/{second.json()['id']}/creative",
        headers=auth(token, "meta-campaign-variant-image-0001"),
        files={"creative": ("cost.png", b"\x89PNG\r\n\x1a\ncost", "image/png")},
    )
    assert second_image.status_code == 200, second_image.text

    prepared = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/prepare",
        headers=auth(token, "meta-campaign-prepare-0001"),
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["status"] == "PREPARING"
    assert prepared.json()["currency"] is None
    assert prepared.json()["externalAdId"] is None
    assert not FakeMetaClient.posts
    blocked_during_preparation = await client.put(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-change-preparing-0001"),
        json={
            "adAccountId": "123456",
            "pageId": "page-1",
            "instagramActorId": "ig-1",
            "defaultLeadFormId": "instant-form-1",
            "accessToken": "rotated-meta-access-token-for-tests",
            "appSecret": "rotated-app-secret-for-tests",  # pragma: allowlist secret
            "verifyToken": "rotated-verify-token-for-tests",
        },
    )
    assert blocked_during_preparation.status_code == 409
    blocked_disconnect_during_preparation = await client.delete(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-disconnect-preparing-0001"),
    )
    assert blocked_disconnect_during_preparation.status_code == 409
    async with SessionFactory() as session:
        preparation_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == social_campaigns.CAMPAIGN_PREPARATION_EVENT,
                OutboxEvent.aggregate_id == campaign["id"],
            )
        )
        assert preparation_event is not None
        preparation_message = OutboxMessage(
            event_id=preparation_event.id,
            tenant_id=preparation_event.tenant_id,
            event_type=preparation_event.event_type,
            aggregate_type=preparation_event.aggregate_type,
            aggregate_id=preparation_event.aggregate_id,
            payload=preparation_event.payload,
            correlation_id=preparation_event.correlation_id,
            attempts=1,
        )
    assert await consume_once(
        consumer_name=CONSUMER_NAME,
        message=preparation_message,
        handler=handle_campaign_preparation,
    )
    assert not await consume_once(
        consumer_name=CONSUMER_NAME,
        message=preparation_message,
        handler=handle_campaign_preparation,
    )
    prepared_campaigns = await client.get("/api/v1/crm/campaigns", headers=auth(token))
    assert prepared_campaigns.status_code == 200
    prepared_campaign = prepared_campaigns.json()[0]
    assert prepared_campaign["status"] == "PREPARED"
    assert prepared_campaign["currency"] == "USD"
    assert prepared_campaign["externalAdId"] == "meta-ad-1"
    creation_statuses = {
        url.rsplit("/", 1)[-1]: data.get("status") for url, data in FakeMetaClient.posts[:5]
    }
    assert creation_statuses["campaigns"] == "PAUSED"
    assert creation_statuses["adsets"] == "PAUSED"
    assert creation_statuses["ads"] == "PAUSED"
    assert sum(url.endswith("/adsets") for url, _data in FakeMetaClient.posts) == 1
    assert sum(url.endswith("/ads") for url, _data in FakeMetaClient.posts) == 2

    rejected = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/activate",
        headers=auth(token, "meta-campaign-activate-0001"),
        json={"confirmed": False},
    )
    assert rejected.status_code == 422
    policy = await client.get("/api/v1/crm/campaigns/policy", headers=auth(token))
    assert policy.status_code == 200, policy.text
    assert policy.json() == {
        "activationEnabled": False,
        "dailyBudgetLimit": "0.00",
        "activeDailyBudget": "0.00",
    }
    blocked_by_kill_switch = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/activate",
        headers=auth(token, "meta-campaign-activate-disabled-0001"),
        json={"confirmed": True},
    )
    assert blocked_by_kill_switch.status_code == 409
    low_policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-campaign-policy-low-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "4.00"},
    )
    assert low_policy.status_code == 200, low_policy.text
    blocked_by_budget = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/activate",
        headers=auth(token, "meta-campaign-activate-budget-0001"),
        json={"confirmed": True},
    )
    assert blocked_by_budget.status_code == 422
    enabled_policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-campaign-policy-enable-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "10.00"},
    )
    assert enabled_policy.status_code == 200, enabled_policy.text
    activated = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/activate",
        headers=auth(token, "meta-campaign-activate-0002"),
        json={"confirmed": True},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVATING"
    assert activated.json()["approvedAt"] is not None
    assert not [data for _url, data in FakeMetaClient.posts if data.get("status") == "ACTIVE"]
    async with SessionFactory() as session:
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == social_campaigns.CAMPAIGN_ACTIVATION_EVENT
            )
        )
        assert event is not None
        message = OutboxMessage(
            event_id=event.id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            correlation_id=event.correlation_id,
            attempts=1,
        )
    assert await consume_once(
        consumer_name=CONSUMER_NAME,
        message=message,
        handler=handle_campaign_activation,
    )
    assert not await consume_once(
        consumer_name=CONSUMER_NAME,
        message=message,
        handler=handle_campaign_activation,
    )
    active_campaigns = await client.get("/api/v1/crm/campaigns", headers=auth(token))
    assert active_campaigns.status_code == 200
    assert active_campaigns.json()[0]["status"] == "ACTIVE"
    active_policy = await client.get("/api/v1/crm/campaigns/policy", headers=auth(token))
    assert active_policy.status_code == 200
    assert active_policy.json()["activeDailyBudget"] == "5.00"
    blocked_lower_limit = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-campaign-policy-lower-active-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "4.00"},
    )
    assert blocked_lower_limit.status_code == 409
    activation_order = [
        url.rsplit("/", 1)[-1]
        for url, data in FakeMetaClient.posts
        if data.get("status") == "ACTIVE"
    ]
    assert activation_order == ["meta-ad-1", "meta-ad-2", "meta-adset-1", "meta-campaign-1"]
    blocked_prepare = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/prepare",
        headers=auth(token, "meta-campaign-prepare-active-0001"),
    )
    assert blocked_prepare.status_code == 409
    blocked_disconnect = await client.delete(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-disconnect-active-0001"),
    )
    assert blocked_disconnect.status_code == 409
    blocked_reconfigure = await client.put(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-change-active-0001"),
        json={
            "adAccountId": "different-account",
            "pageId": "different-page",
            "defaultLeadFormId": "different-form",
            "accessToken": "different-meta-access-token-for-tests",
            "appSecret": "different-app-secret-for-tests",  # pragma: allowlist secret
            "verifyToken": "different-verify-token-for-tests",
        },
    )
    assert blocked_reconfigure.status_code == 409

    captured = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "meta-variant-lead-capture-0001"),
        json={
            "source": "META_LEAD_AD",
            "sourceExternalId": "variant-lead-1",
            "partyName": "Responsable AWS",
            "partyEmail": "aws@example.com",
            "title": "Revisión AWS",
            "campaignId": "meta-campaign-1",
            "campaignName": "Campaña de demostración",
            "adId": "meta-ad-1",
            "utmSource": "meta",
            "utmMedium": "paid_social",
            "utmContent": "principal",
            "consentCapturedAt": "2026-08-04T15:30:00Z",
            "consentTextVersion": "meta-form:instant-form-1",
            "campaignVariantId": principal["id"],
            "companyName": "Empresa Uno",
            "jobTitle": "CTO",
            "usesAws": True,
            "decisionAuthority": True,
        },
    )
    assert captured.status_code == 201, captured.text
    qualified = await client.put(
        f"/api/v1/crm/leads/{captured.json()['lead']['id']}/qualification",
        headers=auth(token, "meta-variant-lead-qualify-0001"),
        json={
            "status": "QUALIFIED",
            "companyName": "Empresa Uno",
            "jobTitle": "CTO",
            "usesAws": True,
            "decisionAuthority": True,
            "reason": "Usa AWS y decide sobre la cuenta.",
        },
    )
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["qualificationStatus"] == "QUALIFIED"

    insights = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/insights/sync",
        headers=auth(token, "meta-campaign-insights-0001"),
        json={"days": 3},
    )
    assert insights.status_code == 200, insights.text
    decisions = {item["variant"]["key"]: item for item in insights.json()["variants"]}
    assert decisions["principal"]["ctr"] == "2.00"
    assert decisions["principal"]["cpl"] == "2.00"
    assert decisions["principal"]["qualifiedLeads"] == 1
    assert decisions["principal"]["costPerQualifiedLead"] == "4.00"
    assert decisions["costo"]["ctr"] == "1.00"
    assert decisions["costo"]["cpl"] == "6.00"
    assert decisions["costo"]["costPerQualifiedLead"] is None

    paused_posts_before_cut = len(FakeMetaClient.posts)
    disabled_policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-campaign-policy-disable-0001"),
        json={"activationEnabled": False, "dailyBudgetLimit": "0.00"},
    )
    assert disabled_policy.status_code == 200, disabled_policy.text
    assert disabled_policy.json()["activationEnabled"] is False
    assert len(FakeMetaClient.posts) == paused_posts_before_cut
    async with SessionFactory() as session:
        policy_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == social_campaigns.CAMPAIGN_POLICY_EVENT
            )
        )
        assert policy_event is not None
        policy_message = OutboxMessage(
            event_id=policy_event.id,
            tenant_id=policy_event.tenant_id,
            event_type=policy_event.event_type,
            aggregate_type=policy_event.aggregate_type,
            aggregate_id=policy_event.aggregate_id,
            payload=policy_event.payload,
            correlation_id=policy_event.correlation_id,
            attempts=1,
        )
    assert await consume_once(
        consumer_name=CONSUMER_NAME,
        message=policy_message,
        handler=handle_campaign_policy,
    )
    cut_campaigns = await client.get("/api/v1/crm/campaigns", headers=auth(token))
    assert cut_campaigns.status_code == 200
    assert cut_campaigns.json()[0]["status"] == "PAUSED"
    reenabled_policy = await client.put(
        "/api/v1/crm/campaigns/policy",
        headers=auth(token, "meta-campaign-policy-reenable-0001"),
        json={"activationEnabled": True, "dailyBudgetLimit": "10.00"},
    )
    assert reenabled_policy.status_code == 200, reenabled_policy.text
    FakeMetaClient.fail_active_object_id = "meta-ad-2"
    retry_activation = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/activate",
        headers=auth(token, "meta-campaign-activate-compensate-0001"),
        json={"confirmed": True},
    )
    assert retry_activation.status_code == 200, retry_activation.text
    assert retry_activation.json()["status"] == "ACTIVATING"
    async with SessionFactory() as session:
        retry_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == social_campaigns.CAMPAIGN_ACTIVATION_EVENT,
                OutboxEvent.aggregate_id == campaign["id"],
                OutboxEvent.id != message.event_id,
            )
        )
        assert retry_event is not None
        retry_message = OutboxMessage(
            event_id=retry_event.id,
            tenant_id=retry_event.tenant_id,
            event_type=retry_event.event_type,
            aggregate_type=retry_event.aggregate_type,
            aggregate_id=retry_event.aggregate_id,
            payload=retry_event.payload,
            correlation_id=retry_event.correlation_id,
            attempts=1,
        )
    assert await consume_once(
        consumer_name=CONSUMER_NAME,
        message=retry_message,
        handler=handle_campaign_activation,
    )
    failed_campaigns = await client.get("/api/v1/crm/campaigns", headers=auth(token))
    assert failed_campaigns.status_code == 200
    assert failed_campaigns.json()[0]["status"] == "ERROR"
    assert "Meta objects were paused" in failed_campaigns.json()[0]["lastError"]
    compensation_ids = [
        url.rsplit("/", 1)[-1]
        for url, data in FakeMetaClient.posts
        if data.get("status") == "PAUSED"
    ]
    assert compensation_ids[-4:] == [
        "meta-ad-1",
        "meta-ad-2",
        "meta-adset-1",
        "meta-campaign-1",
    ]
    FakeMetaClient.fail_active_object_id = None
    safe_pause = await client.post(
        f"/api/v1/crm/campaigns/{campaign['id']}/pause",
        headers=auth(token, "meta-campaign-pause-after-error-0001"),
    )
    assert safe_pause.status_code == 200, safe_pause.text
    assert safe_pause.json()["status"] == "PAUSING"
    async with SessionFactory() as session:
        pause_event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == social_campaigns.CAMPAIGN_PAUSE_EVENT,
                OutboxEvent.aggregate_id == campaign["id"],
            )
        )
        assert pause_event is not None
        pause_message = OutboxMessage(
            event_id=pause_event.id,
            tenant_id=pause_event.tenant_id,
            event_type=pause_event.event_type,
            aggregate_type=pause_event.aggregate_type,
            aggregate_id=pause_event.aggregate_id,
            payload=pause_event.payload,
            correlation_id=pause_event.correlation_id,
            attempts=1,
        )
    assert await consume_once(
        consumer_name=CONSUMER_NAME,
        message=pause_message,
        handler=handle_campaign_pause,
    )
    safely_paused = await client.get("/api/v1/crm/campaigns", headers=auth(token))
    assert safely_paused.status_code == 200
    assert safely_paused.json()[0]["status"] == "PAUSED"
    disconnected = await client.delete(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-integration-disconnect-0001"),
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["connected"] is False


async def test_meta_webhook_creates_attributed_lead_once(client, monkeypatch):
    FakeMetaClient.posts = []
    monkeypatch.setattr(social_campaigns.httpx, "AsyncClient", FakeMetaClient)
    token = await token_for(client, ["communications:read", "communications:write", "leads:read"])
    saved = await client.put(
        "/api/v1/crm/integrations/meta-ads",
        headers=auth(token, "meta-webhook-integration-0001"),
        json={
            "adAccountId": "act_123456",
            "pageId": "page-1",
            "defaultLeadFormId": "instant-form-1",
            "accessToken": "meta-access-token-for-tests-123",
            "appSecret": "app-secret-for-tests",  # pragma: allowlist secret
            "verifyToken": "verify-token-for-tests",
        },
    )
    assert saved.status_code == 200, saved.text

    campaign = await client.post(
        "/api/v1/crm/campaigns",
        headers=auth(token, "meta-webhook-campaign-0001"),
        json={
            "name": "Campaña IAERP",
            "dailyBudget": "5.00",
            "primaryText": "Solicita una demo.",
            "headline": "Demo IAERP",
        },
    )
    assert campaign.status_code == 201, campaign.text
    variant = await client.post(
        f"/api/v1/crm/campaigns/{campaign.json()['id']}/variants",
        headers=auth(token, "meta-webhook-variant-0001"),
        json={
            "key": "riesgo",
            "name": "Ángulo riesgo",
            "angle": "RISK",
            "primaryText": "Revisa el riesgo de tu cuenta AWS.",
            "headline": "Revisión AWS",
        },
    )
    assert variant.status_code == 201, variant.text
    async with SessionFactory() as session, session.begin():
        entity = await session.get(SocialCampaignVariant, uuid.UUID(variant.json()["id"]))
        assert entity is not None
        entity.external_ad_id = "meta-ad-1"

    verified = await client.get(
        "/api/v1/crm/webhooks/meta-leads",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token-for-tests",
            "hub.challenge": "challenge-123",
        },
    )
    assert verified.status_code == 200
    assert verified.text == "challenge-123"

    invalid_json = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=b"{",
        headers={"Content-Type": "application/json"},
    )
    assert invalid_json.status_code == 400
    oversized = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413

    payload = {
        "entry": [
            {
                "id": "page-1",
                "changes": [{"field": "leadgen", "value": {"leadgen_id": "lead-response-1"}}],
            }
        ]
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"app-secret-for-tests", raw, hashlib.sha256).hexdigest()
    too_many_payload = {
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {"field": "leadgen", "value": {"leadgen_id": f"lead-{index}"}}
                    for index in range(101)
                ],
            }
        ]
    }
    too_many_raw = json.dumps(too_many_payload, separators=(",", ":")).encode()
    too_many_signature = (
        "sha256=" + hmac.new(b"app-secret-for-tests", too_many_raw, hashlib.sha256).hexdigest()
    )
    too_many = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=too_many_raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": too_many_signature,
        },
    )
    assert too_many.status_code == 413

    first = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"leadsCreated": 1, "duplicates": 0, "errors": 0}
    repeated = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {"leadsCreated": 0, "duplicates": 1, "errors": 0}

    leads = await client.get("/api/v1/crm/leads", headers=auth(token))
    assert leads.status_code == 200
    assert leads.json()[0]["status"] == "NEW"
    assert leads.json()[0]["source"] == "META_LEAD_AD"
    assert leads.json()[0]["campaignId"] == "meta-campaign-1"
    assert leads.json()[0]["adId"] == "meta-ad-1"
    assert leads.json()[0]["campaignVariantId"] == variant.json()["id"]
    assert leads.json()[0]["utmContent"] == "riesgo"
    assert leads.json()[0]["companyName"] == "Empresa AWS"
    assert leads.json()[0]["jobTitle"] == "CTO"
    assert leads.json()[0]["usesAws"] is True
    assert leads.json()[0]["decisionAuthority"] is True
    assert leads.json()[0]["party"]["email"] == "ana.campana@example.com"

    invalid = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert invalid.status_code == 401
    monkeypatch.setattr(social_campaigns, "MAX_META_WEBHOOK_REQUESTS_PER_MINUTE", 3)
    rate_limited = await client.post(
        "/api/v1/crm/webhooks/meta-leads",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    assert rate_limited.status_code == 429

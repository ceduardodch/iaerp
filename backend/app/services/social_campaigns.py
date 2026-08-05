from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.crm import (
    Lead,
    MetaAdsIntegration,
    MetaWebhookAttempt,
    SocialCampaign,
    SocialCampaignMetricDaily,
    SocialCampaignPolicy,
    SocialCampaignVariant,
)
from app.models.platform import Tenant
from app.schemas.crm import (
    LeadCampaignCaptureCreate,
    MetaAdsIntegrationRead,
    MetaAdsIntegrationUpdate,
    SocialCampaignCreate,
    SocialCampaignInsightsRead,
    SocialCampaignMetricDailyRead,
    SocialCampaignPolicyRead,
    SocialCampaignPolicyUpdate,
    SocialCampaignVariantCreate,
    SocialCampaignVariantDecisionRead,
    SocialCampaignVariantRead,
)
from app.services import crm, storage
from app.services.fiscal_settings import decrypt_secret, encrypt_secret
from app.services.unit_of_work import append_audit

GRAPH_BASE_URL = "https://graph.facebook.com/v23.0"
MAX_META_LEAD_EVENTS = 100
MAX_META_WEBHOOK_REQUESTS_PER_MINUTE = 120
MONEY_QUANTUM = Decimal("0.01")
CAMPAIGN_ACTIVATION_EVENT = "campaign.activation_requested"
CAMPAIGN_PREPARATION_EVENT = "campaign.preparation_requested"
CAMPAIGN_PAUSE_EVENT = "campaign.pause_requested"
CAMPAIGN_POLICY_EVENT = "campaign.policy_updated"
settings = get_settings()


def _public_api_url() -> str:
    return (settings.PUBLIC_API_URL or f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1").rstrip("/")


def _webhook_url() -> str:
    return f"{_public_api_url()}/crm/webhooks/meta-leads"


def _account_id(value: str) -> str:
    return value if value.startswith("act_") else f"act_{value}"


def _integration_read(entity: MetaAdsIntegration | None) -> MetaAdsIntegrationRead:
    return MetaAdsIntegrationRead(
        connected=bool(entity and entity.active),
        ad_account_id=entity.ad_account_id if entity and entity.active else None,
        page_id=entity.page_id if entity and entity.active else None,
        instagram_actor_id=entity.instagram_actor_id if entity and entity.active else None,
        default_lead_form_id=entity.default_lead_form_id if entity and entity.active else None,
        account_currency=entity.account_currency if entity and entity.active else None,
        account_timezone=entity.account_timezone if entity and entity.active else None,
        webhook_url=_webhook_url(),
    )


async def get_integration(session: AsyncSession, context: AuthContext) -> MetaAdsIntegrationRead:
    entity = await session.scalar(
        select(MetaAdsIntegration).where(MetaAdsIntegration.tenant_id == context.tenant_id)
    )
    return _integration_read(entity)


async def save_integration(
    session: AsyncSession, context: AuthContext, data: MetaAdsIntegrationUpdate
) -> MetaAdsIntegrationRead:
    entity = await session.scalar(
        select(MetaAdsIntegration).where(MetaAdsIntegration.tenant_id == context.tenant_id)
    )
    protected_campaign = await session.scalar(
        select(SocialCampaign.id).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.status.in_({"PREPARING", "ACTIVATING", "ACTIVE", "PAUSING"}),
        )
    )
    if protected_campaign is not None:
        raise HTTPException(
            status_code=409,
            detail="Pause campaigns before changing Meta credentials or assets",
        )
    if entity is None:
        entity = MetaAdsIntegration(tenant_id=context.tenant_id)
        session.add(entity)
    entity.ad_account_id = _account_id(data.ad_account_id)
    entity.page_id = data.page_id
    entity.instagram_actor_id = data.instagram_actor_id
    entity.default_lead_form_id = data.default_lead_form_id
    entity.access_token_encrypted = encrypt_secret(data.access_token)
    entity.app_secret_encrypted = encrypt_secret(data.app_secret)
    entity.verify_token_encrypted = encrypt_secret(data.verify_token)
    entity.active = True
    await session.flush()
    return _integration_read(entity)


async def disconnect_integration(session: AsyncSession, context: AuthContext) -> None:
    active_campaign = await session.scalar(
        select(SocialCampaign.id).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.status.in_({"PREPARING", "ACTIVATING", "ACTIVE", "PAUSING"}),
        )
    )
    if active_campaign is not None:
        raise HTTPException(
            status_code=409,
            detail="Pause active campaigns before disconnecting Meta Ads",
        )
    entity = await session.scalar(
        select(MetaAdsIntegration).where(MetaAdsIntegration.tenant_id == context.tenant_id)
    )
    if entity:
        entity.active = False
        await session.flush()


async def list_campaigns(session: AsyncSession, context: AuthContext) -> list[SocialCampaign]:
    return list(
        await session.scalars(
            select(SocialCampaign)
            .where(SocialCampaign.tenant_id == context.tenant_id)
            .order_by(SocialCampaign.created_at.desc())
        )
    )


async def get_campaign_policy(
    session: AsyncSession,
    context: AuthContext,
) -> SocialCampaignPolicyRead:
    policy = await session.get(SocialCampaignPolicy, context.tenant_id)
    active_budget = await session.scalar(
        select(func.coalesce(func.sum(SocialCampaign.daily_budget), Decimal("0.00"))).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.status.in_({"ACTIVATING", "ACTIVE", "PAUSING"}),
        )
    )
    return SocialCampaignPolicyRead(
        activation_enabled=policy.activation_enabled if policy else False,
        daily_budget_limit=policy.daily_budget_limit if policy else Decimal("0.00"),
        active_daily_budget=Decimal(active_budget or 0).quantize(MONEY_QUANTUM),
    )


async def update_campaign_policy(
    session: AsyncSession,
    context: AuthContext,
    data: SocialCampaignPolicyUpdate,
) -> SocialCampaignPolicyRead:
    if context.actor_type != "USER" or not context.roles.intersection({"owner", "admin"}):
        raise HTTPException(status_code=403, detail="Only an owner can change campaign spending")
    policy = await session.get(SocialCampaignPolicy, context.tenant_id)
    if policy is None:
        policy = SocialCampaignPolicy(tenant_id=context.tenant_id)
        session.add(policy)
    active_budget = await session.scalar(
        select(func.coalesce(func.sum(SocialCampaign.daily_budget), Decimal("0.00"))).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.status.in_({"ACTIVATING", "ACTIVE", "PAUSING"}),
        )
    )
    current_active = Decimal(active_budget or 0).quantize(MONEY_QUANTUM)
    if data.activation_enabled and data.daily_budget_limit < current_active:
        raise HTTPException(
            status_code=409,
            detail="Pause campaigns before lowering the limit below active daily spend",
        )
    policy.activation_enabled = data.activation_enabled
    policy.daily_budget_limit = data.daily_budget_limit
    if not data.activation_enabled:
        campaigns = await session.scalars(
            select(SocialCampaign).where(
                SocialCampaign.tenant_id == context.tenant_id,
                SocialCampaign.status.in_({"ACTIVATING", "ACTIVE"}),
            )
        )
        for campaign in campaigns:
            campaign.status = "PAUSING"
            campaign.last_error = None
    await session.flush()
    return SocialCampaignPolicyRead(
        activation_enabled=policy.activation_enabled,
        daily_budget_limit=policy.daily_budget_limit,
        active_daily_budget=current_active,
    )


async def get_campaign(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> SocialCampaign:
    entity = await session.scalar(
        select(SocialCampaign).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.id == campaign_id,
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return entity


async def create_campaign(
    session: AsyncSession, context: AuthContext, data: SocialCampaignCreate
) -> SocialCampaign:
    entity = SocialCampaign(
        tenant_id=context.tenant_id,
        provider="META",
        status="DRAFT",
        currency=None,
        **data.model_dump(by_alias=False),
    )
    session.add(entity)
    await session.flush()
    return entity


async def list_variants(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> list[SocialCampaignVariant]:
    await get_campaign(session, context, campaign_id)
    return list(
        await session.scalars(
            select(SocialCampaignVariant)
            .where(
                SocialCampaignVariant.tenant_id == context.tenant_id,
                SocialCampaignVariant.campaign_id == campaign_id,
            )
            .order_by(SocialCampaignVariant.position, SocialCampaignVariant.created_at)
        )
    )


async def get_variant(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> SocialCampaignVariant:
    entity = await session.scalar(
        select(SocialCampaignVariant).where(
            SocialCampaignVariant.tenant_id == context.tenant_id,
            SocialCampaignVariant.campaign_id == campaign_id,
            SocialCampaignVariant.id == variant_id,
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Campaign variant not found")
    return entity


async def create_variant(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    data: SocialCampaignVariantCreate,
) -> SocialCampaignVariant:
    campaign = await get_campaign(session, context, campaign_id)
    if campaign.status not in {"DRAFT", "ERROR"}:
        raise HTTPException(
            status_code=409, detail="Variants can only be added to a draft campaign"
        )
    existing = await session.scalar(
        select(SocialCampaignVariant).where(
            SocialCampaignVariant.tenant_id == context.tenant_id,
            SocialCampaignVariant.campaign_id == campaign_id,
            SocialCampaignVariant.key == data.key,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Campaign variant key already exists")
    position = await session.scalar(
        select(func.max(SocialCampaignVariant.position)).where(
            SocialCampaignVariant.tenant_id == context.tenant_id,
            SocialCampaignVariant.campaign_id == campaign_id,
        )
    )
    entity = SocialCampaignVariant(
        tenant_id=context.tenant_id,
        campaign_id=campaign_id,
        position=(position or 0) + 1,
        **data.model_dump(by_alias=False),
    )
    session.add(entity)
    campaign.status = "DRAFT"
    campaign.last_error = None
    await session.flush()
    await session.refresh(entity)
    return entity


def _validate_creative(data: bytes, content_type: str) -> tuple[str, str]:
    if content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=422, detail="Creative must be a JPEG or PNG image")
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Creative must be between 1 byte and 5 MB")
    signature_ok = (
        data.startswith(b"\xff\xd8\xff")
        if content_type == "image/jpeg"
        else data.startswith(b"\x89PNG\r\n\x1a\n")
    )
    if not signature_ok:
        raise HTTPException(
            status_code=422, detail="Creative content does not match its image type"
        )
    return hashlib.sha256(data).hexdigest(), "jpg" if content_type == "image/jpeg" else "png"


async def upload_variant_creative(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    variant_id: uuid.UUID,
    *,
    data: bytes,
    content_type: str,
) -> SocialCampaignVariant:
    campaign = await get_campaign(session, context, campaign_id)
    if campaign.status not in {"DRAFT", "ERROR"}:
        raise HTTPException(status_code=409, detail="Creative can only change on a draft campaign")
    variant = await get_variant(session, context, campaign_id, variant_id)
    digest, extension = _validate_creative(data, content_type)
    object_key = (
        f"tenants/{context.tenant_id}/crm/campaigns/{campaign.id}/"
        f"variants/{variant.id}/{digest}.{extension}"
    )
    await storage.upload_private_object(
        object_key=object_key,
        data=data,
        content_type=content_type,
    )
    variant.creative_object_key = object_key
    variant.creative_content_type = content_type
    variant.creative_sha256 = digest
    variant.external_creative_id = None
    variant.external_ad_id = None
    campaign.status = "DRAFT"
    campaign.last_error = None
    await session.flush()
    await session.refresh(variant)
    return variant


async def upload_creative(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    *,
    data: bytes,
    content_type: str,
) -> SocialCampaign:
    entity = await get_campaign(session, context, campaign_id)
    variant = await session.scalar(
        select(SocialCampaignVariant).where(
            SocialCampaignVariant.tenant_id == context.tenant_id,
            SocialCampaignVariant.campaign_id == campaign_id,
            SocialCampaignVariant.key == "principal",
        )
    )
    if variant is None:
        variant = await create_variant(
            session,
            context,
            campaign_id,
            SocialCampaignVariantCreate(
                key="principal",
                name="Principal",
                angle=None,
                primary_text=entity.primary_text,
                headline=entity.headline,
                description=entity.description,
            ),
        )
    variant = await upload_variant_creative(
        session,
        context,
        campaign_id,
        variant.id,
        data=data,
        content_type=content_type,
    )
    entity.creative_object_key = variant.creative_object_key
    entity.creative_content_type = variant.creative_content_type
    entity.creative_sha256 = variant.creative_sha256
    await session.flush()
    await session.refresh(entity)
    return entity


async def _active_integration(session: AsyncSession, tenant_id: uuid.UUID) -> MetaAdsIntegration:
    entity = await session.scalar(
        select(MetaAdsIntegration).where(
            MetaAdsIntegration.tenant_id == tenant_id,
            MetaAdsIntegration.active.is_(True),
        )
    )
    if entity is None:
        raise HTTPException(status_code=422, detail="Meta Ads is not connected")
    return entity


def _meta_error(response: httpx.Response) -> HTTPException:
    message = "Meta rejected the campaign operation"
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])[:500]
    except ValueError:
        pass
    return HTTPException(status_code=502, detail=message)


async def _post_meta(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    data: dict[str, object],
    *,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> dict[str, Any]:
    encoded = {
        key: json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else value
        for key, value in data.items()
    }
    response = await client.post(
        f"{GRAPH_BASE_URL}/{path.lstrip('/')}",
        data={"access_token": token, **encoded},
        files=files,
    )
    if response.is_error:
        raise _meta_error(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Meta returned an invalid response")
    return payload


async def _find_meta_object(
    client: httpx.AsyncClient,
    path: str,
    token: str,
    *,
    name: str,
) -> str | None:
    after: str | None = None
    for _page in range(20):
        params: dict[str, str | int] = {
            "fields": "id,name",
            "limit": 100,
            "access_token": token,
        }
        if after:
            params["after"] = after
        response = await client.get(
            f"{GRAPH_BASE_URL}/{path.lstrip('/')}",
            params=params,
        )
        if response.is_error:
            raise _meta_error(response)
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        match = next(
            (item for item in items if isinstance(item, dict) and item.get("name") == name),
            None,
        )
        if isinstance(match, dict) and match.get("id"):
            return str(match["id"])
        paging = payload.get("paging") if isinstance(payload, dict) else None
        cursors = paging.get("cursors") if isinstance(paging, dict) else None
        next_after = cursors.get("after") if isinstance(cursors, dict) else None
        if not isinstance(next_after, str) or not next_after or next_after == after:
            return None
        after = next_after
    return None


async def _refresh_account_metadata(
    client: httpx.AsyncClient,
    integration: MetaAdsIntegration,
    token: str,
) -> None:
    response = await client.get(
        f"{GRAPH_BASE_URL}/{integration.ad_account_id}",
        params={"fields": "id,currency,timezone_name", "access_token": token},
    )
    if response.is_error:
        raise _meta_error(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Meta returned invalid account metadata")
    currency = str(payload.get("currency") or "").upper()
    timezone_name = str(payload.get("timezone_name") or "")
    if len(currency) != 3:
        raise HTTPException(status_code=502, detail="Meta account currency is unavailable")
    integration.account_currency = currency
    integration.account_timezone = timezone_name or "UTC"


async def prepare_campaign(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> SocialCampaign:
    entity = await get_campaign(session, context, campaign_id)
    if entity.status not in {"DRAFT", "ERROR"}:
        raise HTTPException(
            status_code=409,
            detail="Only draft or failed campaigns can be prepared",
        )
    integration = await _active_integration(session, context.tenant_id)
    variants = await list_variants(session, context, campaign_id)
    if not variants:
        raise HTTPException(status_code=422, detail="Create at least one campaign variant")
    if any(
        not variant.creative_object_key or not variant.creative_content_type for variant in variants
    ):
        raise HTTPException(status_code=422, detail="Every campaign variant needs an image")
    lead_form_id = entity.lead_form_id or integration.default_lead_form_id
    if not lead_form_id:
        raise HTTPException(status_code=422, detail="A Meta instant form is required")
    entity.status = "PREPARING"
    entity.lead_form_id = lead_form_id
    entity.last_error = None
    await session.flush()
    await session.refresh(entity)
    return entity


async def apply_campaign_preparation(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> SocialCampaign:
    entity = await get_campaign(session, context, campaign_id)
    if entity.status == "PREPARED":
        return entity
    if entity.status != "PREPARING":
        return entity
    integration = await _active_integration(session, context.tenant_id)
    variants = await list_variants(session, context, campaign_id)
    if not variants or any(
        not variant.creative_object_key or not variant.creative_content_type for variant in variants
    ):
        entity.status = "ERROR"
        entity.last_error = "Every campaign variant needs an image"
        await session.flush()
        return entity
    lead_form_id = entity.lead_form_id or integration.default_lead_form_id
    if not lead_form_id:
        entity.status = "ERROR"
        entity.last_error = "A Meta instant form is required"
        await session.flush()
        return entity
    token = decrypt_secret(integration.access_token_encrypted)
    stable = str(entity.id)
    campaign_name = f"IAERP {entity.name} [{stable}]"
    adset_name = f"IAERP {entity.name} - Audiencia [{stable}]"
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            await _refresh_account_metadata(client, integration, token)
            entity.currency = integration.account_currency
            if not entity.external_campaign_id:
                entity.external_campaign_id = await _find_meta_object(
                    client,
                    f"{integration.ad_account_id}/campaigns",
                    token,
                    name=campaign_name,
                )
                if not entity.external_campaign_id:
                    result = await _post_meta(
                        client,
                        f"{integration.ad_account_id}/campaigns",
                        token,
                        {
                            "name": campaign_name,
                            "objective": "OUTCOME_LEADS",
                            "buying_type": "AUCTION",
                            "special_ad_categories": [],
                            "status": "PAUSED",
                        },
                    )
                    entity.external_campaign_id = str(result["id"])
                await session.flush()
            if not entity.external_adset_id:
                entity.external_adset_id = await _find_meta_object(
                    client,
                    f"{entity.external_campaign_id}/adsets",
                    token,
                    name=adset_name,
                )
                if not entity.external_adset_id:
                    result = await _post_meta(
                        client,
                        f"{integration.ad_account_id}/adsets",
                        token,
                        {
                            "name": adset_name,
                            "campaign_id": entity.external_campaign_id or "",
                            "daily_budget": int(entity.daily_budget * Decimal("100")),
                            "billing_event": "IMPRESSIONS",
                            "optimization_goal": "LEAD_GENERATION",
                            "destination_type": "ON_AD",
                            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                            "promoted_object": {"page_id": integration.page_id},
                            "targeting": {
                                "age_min": entity.age_min,
                                "age_max": entity.age_max,
                                "geo_locations": {"countries": entity.countries},
                            },
                            "status": "PAUSED",
                        },
                    )
                    entity.external_adset_id = str(result["id"])
                await session.flush()
            for variant in variants:
                variant_stable = str(variant.id)
                creative_name = (
                    f"IAERP {entity.name} - {variant.name} - Creativo [{stable}:{variant_stable}]"
                )
                ad_name = f"IAERP {entity.name} - {variant.name} [{stable}:{variant_stable}]"
                if not variant.external_creative_id:
                    image = await storage.download_artifact(
                        object_key=variant.creative_object_key or ""
                    )
                    extension = "jpg" if variant.creative_content_type == "image/jpeg" else "png"
                    image_result = await _post_meta(
                        client,
                        f"{integration.ad_account_id}/adimages",
                        token,
                        {},
                        files={
                            "filename": (
                                f"campaign-{stable}-{variant.key}.{extension}",
                                image,
                                variant.creative_content_type or "application/octet-stream",
                            )
                        },
                    )
                    images = image_result.get("images")
                    first_image = (
                        next(iter(images.values()), None) if isinstance(images, dict) else None
                    )
                    image_hash = first_image.get("hash") if isinstance(first_image, dict) else None
                    if not image_hash:
                        raise HTTPException(
                            status_code=502,
                            detail=f"Meta did not return an image hash for {variant.name}",
                        )
                    story: dict[str, object] = {
                        "page_id": integration.page_id,
                        "link_data": {
                            "link": f"https://www.facebook.com/{integration.page_id}",
                            "image_hash": image_hash,
                            "message": variant.primary_text,
                            "name": variant.headline,
                            "description": variant.description or "",
                            "call_to_action": {
                                "type": "SIGN_UP",
                                "value": {"lead_gen_form_id": lead_form_id},
                            },
                        },
                    }
                    if integration.instagram_actor_id:
                        story["instagram_actor_id"] = integration.instagram_actor_id
                    variant.external_creative_id = await _find_meta_object(
                        client,
                        f"{integration.ad_account_id}/adcreatives",
                        token,
                        name=creative_name,
                    )
                    if not variant.external_creative_id:
                        result = await _post_meta(
                            client,
                            f"{integration.ad_account_id}/adcreatives",
                            token,
                            {"name": creative_name, "object_story_spec": story},
                        )
                        variant.external_creative_id = str(result["id"])
                if not variant.external_ad_id:
                    variant.external_ad_id = await _find_meta_object(
                        client,
                        f"{integration.ad_account_id}/ads",
                        token,
                        name=ad_name,
                    )
                    if not variant.external_ad_id:
                        result = await _post_meta(
                            client,
                            f"{integration.ad_account_id}/ads",
                            token,
                            {
                                "name": ad_name,
                                "adset_id": entity.external_adset_id or "",
                                "creative": {"creative_id": variant.external_creative_id},
                                "status": "PAUSED",
                            },
                        )
                        variant.external_ad_id = str(result["id"])
                await session.flush()
            first = variants[0]
            entity.external_creative_id = first.external_creative_id
            entity.external_ad_id = first.external_ad_id
    except (HTTPException, httpx.HTTPError) as exc:
        entity.status = "ERROR"
        entity.last_error = (
            str(exc.detail) if isinstance(exc, HTTPException) else type(exc).__name__
        )[:1000]
        await session.flush()
        await session.refresh(entity)
        return entity
    entity.status = "PREPARED"
    entity.last_error = None
    entity.lead_form_id = lead_form_id
    await session.flush()
    await session.refresh(entity)
    return entity


async def activate_campaign(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> SocialCampaign:
    entity = await get_campaign(session, context, campaign_id)
    if context.actor_type != "USER" or not context.roles.intersection({"owner", "admin"}):
        raise HTTPException(status_code=403, detail="Only an owner can activate campaign spending")
    policy = await session.get(SocialCampaignPolicy, context.tenant_id)
    if policy is None or not policy.activation_enabled:
        raise HTTPException(
            status_code=409,
            detail="Campaign activation is disabled for this tenant",
        )
    active_budget = await session.scalar(
        select(func.coalesce(func.sum(SocialCampaign.daily_budget), Decimal("0.00"))).where(
            SocialCampaign.tenant_id == context.tenant_id,
            SocialCampaign.status.in_({"ACTIVATING", "ACTIVE", "PAUSING"}),
            SocialCampaign.id != campaign_id,
        )
    )
    if Decimal(active_budget or 0) + entity.daily_budget > policy.daily_budget_limit:
        raise HTTPException(
            status_code=422,
            detail="Campaign would exceed the tenant daily budget limit",
        )
    await _active_integration(session, context.tenant_id)
    if entity.status not in {"PREPARED", "PAUSED"} or not all(
        [entity.external_campaign_id, entity.external_adset_id, entity.external_ad_id]
    ):
        raise HTTPException(status_code=409, detail="Campaign is not ready for activation")
    variants = await list_variants(session, context, campaign_id)
    ad_ids = [variant.external_ad_id for variant in variants]
    if not ad_ids or any(not ad_id for ad_id in ad_ids):
        raise HTTPException(status_code=409, detail="Every campaign variant must be prepared")
    now = datetime.now(UTC)
    entity.status = "ACTIVATING"
    entity.approved_at = now
    entity.approved_by = context.actor_id
    entity.last_error = None
    await session.flush()
    await session.refresh(entity)
    return entity


async def apply_campaign_activation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> SocialCampaign | None:
    """Aplica en Meta una intención ya confirmada y guardada en el outbox."""

    await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    entity = await session.scalar(
        select(SocialCampaign)
        .where(
            SocialCampaign.tenant_id == tenant_id,
            SocialCampaign.id == campaign_id,
        )
        .with_for_update()
    )
    if entity is None or entity.status == "ACTIVE":
        return entity
    if entity.status != "ACTIVATING":
        return entity
    policy = await session.get(SocialCampaignPolicy, tenant_id)
    if policy is None or not policy.activation_enabled:
        entity.status = "PAUSED"
        entity.paused_at = datetime.now(UTC)
        entity.last_error = "Activation cancelled because campaign spending is disabled"
        await session.flush()
        return entity
    integration = await _active_integration(session, tenant_id)
    variants = list(
        await session.scalars(
            select(SocialCampaignVariant)
            .where(
                SocialCampaignVariant.tenant_id == tenant_id,
                SocialCampaignVariant.campaign_id == campaign_id,
            )
            .order_by(SocialCampaignVariant.position)
        )
    )
    ad_ids = [variant.external_ad_id for variant in variants]
    if not ad_ids or any(not ad_id for ad_id in ad_ids):
        entity.status = "ERROR"
        entity.last_error = "Activation stopped because a campaign variant is not prepared"
        await session.flush()
        return entity

    token = decrypt_secret(integration.access_token_encrypted)
    object_ids = [*ad_ids, entity.external_adset_id, entity.external_campaign_id]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Children are enabled while the parent remains paused. The parent
            # campaign is the final switch that can start delivery and spend.
            for object_id in object_ids:
                await _post_meta(client, object_id or "", token, {"status": "ACTIVE"})
    except (HTTPException, httpx.HTTPError) as exc:
        compensation_ok = True
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                for object_id in filter(None, object_ids):
                    await _post_meta(client, object_id, token, {"status": "PAUSED"})
        except (HTTPException, httpx.HTTPError):
            compensation_ok = False
        detail = str(exc.detail) if isinstance(exc, HTTPException) else type(exc).__name__
        entity.status = "ERROR"
        entity.last_error = (
            f"Activation failed; Meta objects were paused. {detail}"
            if compensation_ok
            else f"Activation state is uncertain; pause it again before retrying. {detail}"
        )[:1000]
        await session.flush()
        return entity

    entity.status = "ACTIVE"
    entity.activated_at = datetime.now(UTC)
    entity.last_error = None
    await session.flush()
    return entity


async def pause_campaign(
    session: AsyncSession, context: AuthContext, campaign_id: uuid.UUID
) -> SocialCampaign:
    entity = await get_campaign(session, context, campaign_id)
    if not entity.external_campaign_id:
        raise HTTPException(status_code=409, detail="Campaign has not been prepared")
    if entity.status == "PAUSED":
        return entity
    entity.status = "PAUSING"
    entity.last_error = None
    await session.flush()
    await session.refresh(entity)
    return entity


async def apply_campaign_pause(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> SocialCampaign | None:
    """Pausa en Meta una intención ya confirmada y guardada en el outbox."""

    entity = await session.scalar(
        select(SocialCampaign)
        .where(
            SocialCampaign.tenant_id == tenant_id,
            SocialCampaign.id == campaign_id,
        )
        .with_for_update()
    )
    if entity is None or entity.status == "PAUSED":
        return entity
    if entity.status != "PAUSING":
        return entity
    integration = await _active_integration(session, tenant_id)
    token = decrypt_secret(integration.access_token_encrypted)
    variants = list(
        await session.scalars(
            select(SocialCampaignVariant).where(
                SocialCampaignVariant.tenant_id == tenant_id,
                SocialCampaignVariant.campaign_id == campaign_id,
            )
        )
    )
    async with httpx.AsyncClient(timeout=30) as client:
        for object_id in filter(
            None,
            [
                *(variant.external_ad_id for variant in variants),
                entity.external_adset_id,
                entity.external_campaign_id,
            ],
        ):
            await _post_meta(client, object_id, token, {"status": "PAUSED"})
    entity.status = "PAUSED"
    entity.paused_at = datetime.now(UTC)
    entity.last_error = None
    await session.flush()
    return entity


async def apply_campaign_policy(session: AsyncSession, *, tenant_id: uuid.UUID) -> None:
    """Ejecuta el corte de gasto después de confirmar la política deshabilitada."""

    policy = await session.get(SocialCampaignPolicy, tenant_id)
    if policy is None or policy.activation_enabled:
        return
    campaign_ids = list(
        await session.scalars(
            select(SocialCampaign.id).where(
                SocialCampaign.tenant_id == tenant_id,
                SocialCampaign.status == "PAUSING",
            )
        )
    )
    for campaign_id in campaign_ids:
        await apply_campaign_pause(session, tenant_id=tenant_id, campaign_id=campaign_id)


def _meta_lead_count(actions: object) -> int:
    if not isinstance(actions, list):
        return 0
    by_type = {
        str(item.get("action_type") or ""): int(Decimal(str(item.get("value") or "0")))
        for item in actions
        if isinstance(item, dict)
    }
    for action_type in (
        "onsite_conversion.lead_grouped",
        "lead",
        "onsite_conversion.lead",
    ):
        if action_type in by_type:
            return by_type[action_type]
    return 0


async def sync_insights(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    *,
    days: int,
) -> SocialCampaignInsightsRead:
    campaign = await get_campaign(session, context, campaign_id)
    integration = await _active_integration(session, context.tenant_id)
    variants = await list_variants(session, context, campaign_id)
    if not variants or any(not variant.external_ad_id for variant in variants):
        raise HTTPException(status_code=409, detail="Prepare every campaign variant first")
    token = decrypt_secret(integration.access_token_encrypted)
    refreshed: list[SocialCampaignMetricDaily] = []
    async with httpx.AsyncClient(timeout=45) as client:
        await _refresh_account_metadata(client, integration, token)
        campaign.currency = integration.account_currency
        try:
            zone = ZoneInfo(integration.account_timezone or "UTC")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        date_to = datetime.now(zone).date()
        date_from = date_to - timedelta(days=days - 1)
        for variant in variants:
            response = await client.get(
                f"{GRAPH_BASE_URL}/{variant.external_ad_id}/insights",
                params={
                    "fields": "date_start,date_stop,spend,impressions,clicks,actions",
                    "time_increment": 1,
                    "time_range": json.dumps(
                        {"since": date_from.isoformat(), "until": date_to.isoformat()},
                        separators=(",", ":"),
                    ),
                    "access_token": token,
                },
            )
            if response.is_error:
                raise _meta_error(response)
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or not row.get("date_start"):
                    continue
                metric_date = datetime.fromisoformat(str(row["date_start"])).date()
                metric = await session.scalar(
                    select(SocialCampaignMetricDaily).where(
                        SocialCampaignMetricDaily.tenant_id == context.tenant_id,
                        SocialCampaignMetricDaily.variant_id == variant.id,
                        SocialCampaignMetricDaily.metric_date == metric_date,
                    )
                )
                if metric is None:
                    metric = SocialCampaignMetricDaily(
                        tenant_id=context.tenant_id,
                        variant_id=variant.id,
                        metric_date=metric_date,
                    )
                    session.add(metric)
                metric.external_ad_id = variant.external_ad_id or ""
                metric.currency = integration.account_currency or ""
                metric.spend = Decimal(str(row.get("spend") or "0"))
                metric.impressions = int(row.get("impressions") or 0)
                metric.clicks = int(row.get("clicks") or 0)
                metric.leads = _meta_lead_count(row.get("actions"))
                refreshed.append(metric)
        await session.flush()
    return await get_campaign_insights(
        session,
        context,
        campaign_id,
        synced_metrics=refreshed,
    )


async def get_campaign_insights(
    session: AsyncSession,
    context: AuthContext,
    campaign_id: uuid.UUID,
    *,
    synced_metrics: list[SocialCampaignMetricDaily] | None = None,
) -> SocialCampaignInsightsRead:
    await get_campaign(session, context, campaign_id)
    variants = await list_variants(session, context, campaign_id)
    metrics = list(
        await session.scalars(
            select(SocialCampaignMetricDaily)
            .join(
                SocialCampaignVariant,
                SocialCampaignVariant.id == SocialCampaignMetricDaily.variant_id,
            )
            .where(
                SocialCampaignMetricDaily.tenant_id == context.tenant_id,
                SocialCampaignVariant.campaign_id == campaign_id,
            )
            .order_by(SocialCampaignMetricDaily.metric_date.desc())
        )
    )
    qualified_rows = await session.execute(
        select(Lead.campaign_variant_id, func.count(Lead.id))
        .join(
            SocialCampaignVariant,
            SocialCampaignVariant.id == Lead.campaign_variant_id,
        )
        .where(
            Lead.tenant_id == context.tenant_id,
            Lead.campaign_variant_id.is_not(None),
            Lead.qualification_status == "QUALIFIED",
            SocialCampaignVariant.campaign_id == campaign_id,
        )
        .group_by(Lead.campaign_variant_id)
    )
    qualified = {row[0]: int(row[1]) for row in qualified_rows}
    by_variant: dict[uuid.UUID, list[SocialCampaignMetricDaily]] = defaultdict(list)
    for metric in metrics:
        by_variant[metric.variant_id].append(metric)
    decisions: list[SocialCampaignVariantDecisionRead] = []
    for variant in variants:
        rows = by_variant[variant.id]
        spend = sum((row.spend for row in rows), Decimal("0"))
        impressions = sum(row.impressions for row in rows)
        clicks = sum(row.clicks for row in rows)
        leads = sum(row.leads for row in rows)
        qualified_leads = qualified.get(variant.id, 0)
        currency = rows[0].currency if rows else None
        decisions.append(
            SocialCampaignVariantDecisionRead(
                variant=SocialCampaignVariantRead.model_validate(variant),
                currency=currency,
                spend=spend,
                impressions=impressions,
                clicks=clicks,
                leads=leads,
                qualified_leads=qualified_leads,
                ctr=(Decimal(clicks) * Decimal("100") / Decimal(impressions)).quantize(
                    Decimal("0.01")
                )
                if impressions
                else None,
                cpl=(spend / Decimal(leads)).quantize(Decimal("0.01")) if leads else None,
                cost_per_qualified_lead=(spend / Decimal(qualified_leads)).quantize(Decimal("0.01"))
                if qualified_leads
                else None,
            )
        )
    visible_metrics = synced_metrics if synced_metrics is not None else metrics
    return SocialCampaignInsightsRead(
        campaign_id=campaign_id,
        synced_days=[
            SocialCampaignMetricDailyRead.model_validate(item) for item in visible_metrics
        ],
        variants=decisions,
    )


async def verify_webhook_token(session: AsyncSession, token: str) -> bool:
    entities = await session.scalars(
        select(MetaAdsIntegration).where(MetaAdsIntegration.active.is_(True))
    )
    return any(
        hmac.compare_digest(decrypt_secret(item.verify_token_encrypted), token) for item in entities
    )


def _lead_values(field_data: object) -> dict[str, str]:
    values: dict[str, str] = {}
    if not isinstance(field_data, list):
        return values
    for item in field_data:
        if not isinstance(item, dict) or not isinstance(item.get("values"), list):
            continue
        value_list = item["values"]
        if value_list:
            values[str(item.get("name") or "").lower()] = str(value_list[0])
    return values


def _first_value(values: dict[str, str], *names: str) -> str | None:
    return next((values[name] for name in names if values.get(name)), None)


def _answer_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"yes", "si", "sí", "true", "1", "ya usamos aws"}:
        return True
    if normalized in {"no", "false", "0", "no usamos aws"}:
        return False
    return None


async def _record_webhook_attempt(
    *,
    tenant_id: uuid.UUID,
    page_id: str,
    raw_body: bytes,
) -> bool:
    """Cuenta cada intento firmado en una transacción independiente."""

    async with SessionFactory() as rate_session, rate_session.begin():
        await rate_session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
        recent_attempts = await rate_session.scalar(
            select(func.count(MetaWebhookAttempt.id)).where(
                MetaWebhookAttempt.tenant_id == tenant_id,
                MetaWebhookAttempt.created_at >= datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        rate_session.add(
            MetaWebhookAttempt(
                tenant_id=tenant_id,
                page_id=page_id,
                request_sha256=hashlib.sha256(raw_body).hexdigest(),
            )
        )
        return int(recent_attempts or 0) < MAX_META_WEBHOOK_REQUESTS_PER_MINUTE


async def process_lead_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    signature: str,
    payload: dict[str, object],
) -> dict[str, int]:
    events: list[tuple[str, str]] = []
    page_ids: list[str] = []
    entries = payload.get("entry")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            page_id = str(entry.get("id") or "")
            if page_id:
                page_ids.append(page_id)
            for change in entry.get("changes", []):
                if not isinstance(change, dict) or change.get("field") != "leadgen":
                    continue
                value = change.get("value")
                if isinstance(value, dict) and value.get("leadgen_id"):
                    events.append((page_id, str(value["leadgen_id"])))
    reference_page_id = events[0][0] if events else (page_ids[0] if page_ids else "")
    if not reference_page_id:
        raise HTTPException(status_code=400, detail="Meta webhook page is missing")
    integration = await session.scalar(
        select(MetaAdsIntegration).where(
            MetaAdsIntegration.page_id == reference_page_id,
            MetaAdsIntegration.active.is_(True),
        )
    )
    if integration is None:
        raise HTTPException(status_code=404, detail="Meta Ads integration not found")
    expected = (
        "sha256="
        + hmac.new(
            decrypt_secret(integration.app_secret_encrypted).encode(), raw_body, hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Meta webhook signature")
    if not await _record_webhook_attempt(
        tenant_id=integration.tenant_id,
        page_id=reference_page_id,
        raw_body=raw_body,
    ):
        raise HTTPException(status_code=429, detail="Meta webhook rate limit exceeded")
    if len(events) > MAX_META_LEAD_EVENTS:
        raise HTTPException(status_code=413, detail="Meta webhook contains too many lead events")
    await session.scalar(
        select(Tenant.id).where(Tenant.id == integration.tenant_id).with_for_update()
    )
    context = AuthContext(
        actor_id=f"meta-ads:{integration.id}",
        actor_type="SERVICE_ACCOUNT",
        tenant_id=integration.tenant_id,
        roles=frozenset({"connector"}),
        scopes=frozenset({"leads:write"}),
        token_id=events[0][1] if events else hashlib.sha256(raw_body).hexdigest(),
    )
    token = decrypt_secret(integration.access_token_encrypted)
    created = duplicates = errors = 0
    captured_ids: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for page_id, leadgen_id in events:
            if page_id != integration.page_id:
                errors += 1
                continue
            response = await client.get(
                f"{GRAPH_BASE_URL}/{leadgen_id}",
                params={
                    "fields": "id,created_time,field_data,form_id,ad_id",
                    "access_token": token,
                },
            )
            if response.is_error:
                errors += 1
                continue
            lead_payload = response.json()
            values = _lead_values(lead_payload.get("field_data"))
            email = values.get("email")
            phone = values.get("phone_number") or values.get("phone")
            if not email and not phone:
                errors += 1
                continue
            full_name = values.get("full_name") or " ".join(
                filter(None, [values.get("first_name"), values.get("last_name")])
            )
            full_name = full_name.strip() or "Lead de Meta"
            ad_id = str(lead_payload.get("ad_id") or "")
            campaign_id = campaign_name = None
            variant = None
            if ad_id:
                variant = await session.scalar(
                    select(SocialCampaignVariant).where(
                        SocialCampaignVariant.tenant_id == integration.tenant_id,
                        SocialCampaignVariant.external_ad_id == ad_id,
                    )
                )
                ad_response = await client.get(
                    f"{GRAPH_BASE_URL}/{ad_id}",
                    params={"fields": "id,name,campaign{id,name}", "access_token": token},
                )
                if not ad_response.is_error:
                    ad_payload = ad_response.json()
                    campaign = ad_payload.get("campaign")
                    if isinstance(campaign, dict):
                        campaign_id = str(campaign.get("id") or "") or None
                        campaign_name = str(campaign.get("name") or "") or None
            created_time = lead_payload.get("created_time")
            try:
                consent_at = datetime.fromisoformat(str(created_time).replace("Z", "+00:00"))
            except ValueError:
                consent_at = datetime.now(UTC)
            lead, was_created, _reason = await crm.capture_campaign_lead(
                session,
                context,
                LeadCampaignCaptureCreate(
                    source="META_LEAD_AD",
                    source_external_id=leadgen_id,
                    party_name=full_name,
                    party_email=email,
                    party_phone=phone,
                    title=f"Lead de {campaign_name or 'Meta'}",
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    ad_id=ad_id or None,
                    utm_source="meta",
                    utm_medium="paid_social",
                    utm_campaign=campaign_name,
                    utm_content=variant.key if variant else None,
                    consent_captured_at=consent_at,
                    consent_text_version=f"meta-form:{lead_payload.get('form_id') or 'unknown'}",
                    campaign_variant_id=variant.id if variant else None,
                    company_name=_first_value(values, "company_name", "company", "empresa"),
                    job_title=_first_value(values, "job_title", "role", "cargo"),
                    uses_aws=_answer_bool(
                        _first_value(values, "uses_aws", "already_uses_aws", "usa_aws")
                    ),
                    decision_authority=_answer_bool(
                        _first_value(
                            values,
                            "decision_authority",
                            "is_decision_maker",
                            "acceso_decisor",
                        )
                    ),
                ),
            )
            if was_created:
                created += 1
                captured_ids.append(str(lead.id))
            else:
                duplicates += 1
    await append_audit(
        session,
        context=context,
        action="lead.meta_webhook_processed",
        entity_type="lead",
        entity_id=captured_ids[0] if len(captured_ids) == 1 else None,
        correlation_id=str(uuid.uuid4()),
        idempotency_key="meta-leads:" + hashlib.sha256(raw_body).hexdigest(),
        details={
            "events": len(events),
            "created": created,
            "duplicates": duplicates,
            "errors": errors,
        },
    )
    return {"leadsCreated": created, "duplicates": duplicates, "errors": errors}

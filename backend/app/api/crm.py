import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.models.crm import LeadStatus, SocialCampaign
from app.schemas.crm import (
    ActionQueueRead,
    EvolutionWhatsAppIntegrationRead,
    EvolutionWhatsAppIntegrationUpdate,
    GmailSyncResult,
    GoogleAuthorizationRead,
    IntegrationStatusRead,
    LeadActivityCreate,
    LeadActivityRead,
    LeadActivityReminderUpdate,
    LeadCampaignCaptureCreate,
    LeadCampaignCaptureRead,
    LeadCreate,
    LeadMessageCreate,
    LeadQualificationUpdate,
    LeadRead,
    LeadStatusUpdate,
    LeadUpdate,
    LeadWithPartyCreate,
    MetaAdsIntegrationRead,
    MetaAdsIntegrationUpdate,
    SocialCampaignActivation,
    SocialCampaignCreate,
    SocialCampaignInsightsRead,
    SocialCampaignInsightsSync,
    SocialCampaignPolicyRead,
    SocialCampaignPolicyUpdate,
    SocialCampaignRead,
    SocialCampaignVariantCreate,
    SocialCampaignVariantRead,
    WhatsAppIntegrationUpdate,
    WhatsAppRoutingUpdate,
)
from app.services import action_queue, crm, crm_integrations, social_campaigns
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/crm", tags=["crm"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]
MAX_META_WEBHOOK_BYTES = 1024 * 1024


@router.get("/integrations", response_model=IntegrationStatusRead)
async def get_integrations(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> IntegrationStatusRead:
    return await crm_integrations.integration_status(session, context)


@router.post("/integrations/google/authorize", response_model=GoogleAuthorizationRead)
async def post_google_authorize(
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> GoogleAuthorizationRead:
    return GoogleAuthorizationRead(
        authorization_url=await crm_integrations.google_authorization_url(context)
    )


@router.get(
    "/campaigns/{campaign_id}/variants",
    response_model=list[SocialCampaignVariantRead],
)
async def get_social_campaign_variants(
    campaign_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> list[SocialCampaignVariantRead]:
    entities = await social_campaigns.list_variants(session, context, campaign_id)
    return [SocialCampaignVariantRead.model_validate(entity) for entity in entities]


@router.post(
    "/campaigns/{campaign_id}/variants",
    response_model=SocialCampaignVariantRead,
    status_code=201,
)
async def post_social_campaign_variant(
    campaign_id: uuid.UUID,
    data: SocialCampaignVariantCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await social_campaigns.create_variant(session, context, campaign_id, data)
        return str(entity.id), SocialCampaignVariantRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.create_variant",
        idempotency_key=idempotency_key,
        request_payload={"campaign_id": str(campaign_id), **data.model_dump(mode="json")},
        action="campaign.variant_created",
        entity_type="social_campaign_variant",
        callback=create,
    )


@router.post(
    "/campaigns/{campaign_id}/variants/{variant_id}/creative",
    response_model=SocialCampaignVariantRead,
)
async def post_social_campaign_variant_creative(
    campaign_id: uuid.UUID,
    variant_id: uuid.UUID,
    creative: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    data = await creative.read(5 * 1024 * 1024 + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await social_campaigns.upload_variant_creative(
            session,
            context,
            campaign_id,
            variant_id,
            data=data,
            content_type=creative.content_type or "application/octet-stream",
        )
        return str(entity.id), SocialCampaignVariantRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.upload_variant_creative",
        idempotency_key=idempotency_key,
        request_payload={
            "campaign_id": str(campaign_id),
            "variant_id": str(variant_id),
            "content_type": creative.content_type,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="campaign.variant_creative_uploaded",
        entity_type="social_campaign_variant",
        callback=upload,
    )


@router.get(
    "/campaigns/{campaign_id}/insights",
    response_model=SocialCampaignInsightsRead,
)
async def get_social_campaign_insights(
    campaign_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> SocialCampaignInsightsRead:
    return await social_campaigns.get_campaign_insights(session, context, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/insights/sync",
    response_model=SocialCampaignInsightsRead,
)
async def post_social_campaign_insights_sync(
    campaign_id: uuid.UUID,
    data: SocialCampaignInsightsSync,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def sync() -> tuple[str, dict[str, object]]:
        result = await social_campaigns.sync_insights(session, context, campaign_id, days=data.days)
        return str(campaign_id), result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.sync_insights",
        idempotency_key=idempotency_key,
        request_payload={"campaign_id": str(campaign_id), **data.model_dump(mode="json")},
        action="campaign.insights_synced",
        entity_type="social_campaign",
        callback=sync,
    )


@router.post("/leads/captures", response_model=LeadCampaignCaptureRead, status_code=201)
async def post_campaign_lead_capture(
    data: LeadCampaignCaptureCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:capture"))],
) -> dict[str, object]:
    """Registra un lead proveniente de un conector de campañas autorizado."""
    await crm.preflight_service_account_request(context, "rest.leads.capture")

    async def capture() -> tuple[str, dict[str, object]]:
        lead, created, duplicate_reason = await crm.capture_campaign_lead(session, context, data)
        response = LeadCampaignCaptureRead(
            lead=LeadRead.model_validate(lead),
            created=created,
            duplicate_reason=duplicate_reason,
        ).model_dump(mode="json", by_alias=True)
        return str(lead.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.capture_campaign",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="lead.campaign_captured",
        entity_type="lead",
        callback=capture,
    )


@router.get("/integrations/google/callback", include_in_schema=False)
async def get_google_callback(
    session: Session,
    state: str = Query(min_length=16),
    code: str = Query(min_length=1),
) -> RedirectResponse:
    await crm_integrations.complete_google_oauth(session, state=state, code=code)
    await session.commit()
    return RedirectResponse(url="/?integration=google-connected#empresa")


@router.delete("/integrations/google", response_model=IntegrationStatusRead)
async def delete_google_integration(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> IntegrationStatusRead:
    await crm_integrations.disconnect_google(session, context)
    await session.commit()
    return await crm_integrations.integration_status(session, context)


@router.put("/integrations/whatsapp", response_model=IntegrationStatusRead)
async def put_whatsapp_integration(
    data: WhatsAppIntegrationUpdate,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> IntegrationStatusRead:
    await crm_integrations.save_whatsapp(session, context, data)
    await session.commit()
    return await crm_integrations.integration_status(session, context)


@router.delete("/integrations/whatsapp", response_model=IntegrationStatusRead)
async def delete_whatsapp_integration(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> IntegrationStatusRead:
    await crm_integrations.disconnect_whatsapp(session, context)
    await session.commit()
    return await crm_integrations.integration_status(session, context)


@router.put("/integrations/whatsapp/evolution", response_model=EvolutionWhatsAppIntegrationRead)
async def put_evolution_whatsapp_integration(
    data: EvolutionWhatsAppIntegrationUpdate,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> EvolutionWhatsAppIntegrationRead:
    result = await crm_integrations.save_evolution_whatsapp(session, context, data)
    await session.commit()
    return result


@router.delete("/integrations/whatsapp/evolution", response_model=IntegrationStatusRead)
async def delete_evolution_whatsapp_integration(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> IntegrationStatusRead:
    await crm_integrations.disconnect_evolution_whatsapp(session, context)
    await session.commit()
    return await crm_integrations.integration_status(session, context)


@router.put("/integrations/whatsapp/routing", response_model=IntegrationStatusRead)
async def put_whatsapp_routing(
    data: WhatsAppRoutingUpdate,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> IntegrationStatusRead:
    await crm_integrations.update_whatsapp_routing(session, context, data)
    await session.commit()
    return await crm_integrations.integration_status(session, context)


@router.get("/webhooks/whatsapp", include_in_schema=False)
async def verify_whatsapp_webhook(
    session: Session,
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    if mode != "subscribe" or not await crm_integrations.verify_whatsapp_token(session, token):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp", include_in_schema=False)
async def receive_whatsapp_webhook(request: Request, session: Session) -> dict[str, int]:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    payload = await request.json()
    created = await crm_integrations.process_whatsapp_webhook(
        session,
        raw_body=raw_body,
        signature=signature,
        payload=payload,
    )
    await session.commit()
    return {"activitiesCreated": created}


@router.get("/integrations/meta-ads", response_model=MetaAdsIntegrationRead)
async def get_meta_ads_integration(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> MetaAdsIntegrationRead:
    return await social_campaigns.get_integration(session, context)


@router.put("/integrations/meta-ads", response_model=MetaAdsIntegrationRead)
async def put_meta_ads_integration(
    data: MetaAdsIntegrationUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def save() -> tuple[str, dict[str, object]]:
        result = await social_campaigns.save_integration(session, context, data)
        return "meta-ads", result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="integrations.meta_ads.save",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="integration.meta_ads_saved",
        entity_type="meta_ads_integration",
        callback=save,
    )


@router.delete("/integrations/meta-ads", response_model=MetaAdsIntegrationRead)
async def delete_meta_ads_integration(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def disconnect() -> tuple[str, dict[str, object]]:
        await social_campaigns.disconnect_integration(session, context)
        result = await social_campaigns.get_integration(session, context)
        return "meta-ads", result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="integrations.meta_ads.disconnect",
        idempotency_key=idempotency_key,
        request_payload={},
        action="integration.meta_ads_disconnected",
        entity_type="meta_ads_integration",
        callback=disconnect,
    )


@router.get("/webhooks/meta-leads", include_in_schema=False)
async def verify_meta_leads_webhook(
    session: Session,
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> PlainTextResponse:
    if mode != "subscribe" or not await social_campaigns.verify_webhook_token(session, token):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return PlainTextResponse(challenge)


@router.post("/webhooks/meta-leads", include_in_schema=False)
async def receive_meta_leads_webhook(request: Request, session: Session) -> dict[str, int]:
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_META_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="Meta webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_META_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Meta webhook payload is too large")
        chunks.append(chunk)
    raw_body = b"".join(chunks)
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Meta webhook JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Meta webhook payload")
    result = await social_campaigns.process_lead_webhook(
        session,
        raw_body=raw_body,
        signature=request.headers.get("X-Hub-Signature-256", ""),
        payload=payload,
    )
    await session.commit()
    return result


@router.get("/campaigns", response_model=list[SocialCampaignRead])
async def get_social_campaigns(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> list[SocialCampaignRead]:
    entities = await social_campaigns.list_campaigns(session, context)
    return [SocialCampaignRead.model_validate(entity) for entity in entities]


@router.get("/campaigns/policy", response_model=SocialCampaignPolicyRead)
async def get_social_campaign_policy(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:read"))],
) -> SocialCampaignPolicyRead:
    return await social_campaigns.get_campaign_policy(session, context)


@router.put("/campaigns/policy", response_model=SocialCampaignPolicyRead)
async def put_social_campaign_policy(
    data: SocialCampaignPolicyUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        result = await social_campaigns.update_campaign_policy(session, context, data)
        return "campaign-policy", result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.policy.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="campaign.policy_updated",
        entity_type="social_campaign_policy",
        callback=update,
        event_type=social_campaigns.CAMPAIGN_POLICY_EVENT,
    )


@router.post("/campaigns", response_model=SocialCampaignRead, status_code=201)
async def post_social_campaign(
    data: SocialCampaignCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await social_campaigns.create_campaign(session, context, data)
        return str(entity.id), SocialCampaignRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="campaign.created",
        entity_type="social_campaign",
        callback=create,
    )


@router.post("/campaigns/{campaign_id}/creative", response_model=SocialCampaignRead)
async def post_social_campaign_creative(
    campaign_id: uuid.UUID,
    creative: Annotated[UploadFile, File()],
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    data = await creative.read(5 * 1024 * 1024 + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await social_campaigns.upload_creative(
            session,
            context,
            campaign_id,
            data=data,
            content_type=creative.content_type or "application/octet-stream",
        )
        return str(entity.id), SocialCampaignRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="campaigns.upload_creative",
        idempotency_key=idempotency_key,
        request_payload={
            "campaign_id": str(campaign_id),
            "content_type": creative.content_type,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="campaign.creative_uploaded",
        entity_type="social_campaign",
        callback=upload,
    )


async def _campaign_action(
    *,
    campaign_id: uuid.UUID,
    action_name: str,
    idempotency_key: str,
    session: AsyncSession,
    context: AuthContext,
    callback: Callable[[AsyncSession, AuthContext, uuid.UUID], Awaitable[SocialCampaign]],
    request_payload: dict[str, object],
    event_type: str | None = None,
) -> dict[str, object]:
    async def run() -> tuple[str, dict[str, object]]:
        entity = await callback(session, context, campaign_id)
        return str(entity.id), SocialCampaignRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation=f"campaigns.{action_name}",
        idempotency_key=idempotency_key,
        request_payload={"campaign_id": str(campaign_id), **request_payload},
        action=f"campaign.{action_name}",
        entity_type="social_campaign",
        callback=run,
        event_type=event_type,
    )


@router.post("/campaigns/{campaign_id}/prepare", response_model=SocialCampaignRead)
async def post_social_campaign_prepare(
    campaign_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    return await _campaign_action(
        campaign_id=campaign_id,
        action_name="prepared",
        idempotency_key=idempotency_key,
        session=session,
        context=context,
        callback=social_campaigns.prepare_campaign,
        request_payload={},
        event_type=social_campaigns.CAMPAIGN_PREPARATION_EVENT,
    )


@router.post("/campaigns/{campaign_id}/activate", response_model=SocialCampaignRead)
async def post_social_campaign_activate(
    campaign_id: uuid.UUID,
    data: SocialCampaignActivation,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    return await _campaign_action(
        campaign_id=campaign_id,
        action_name="activated",
        idempotency_key=idempotency_key,
        session=session,
        context=context,
        callback=social_campaigns.activate_campaign,
        request_payload=data.model_dump(mode="json"),
        event_type=social_campaigns.CAMPAIGN_ACTIVATION_EVENT,
    )


@router.post("/campaigns/{campaign_id}/pause", response_model=SocialCampaignRead)
async def post_social_campaign_pause(
    campaign_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    return await _campaign_action(
        campaign_id=campaign_id,
        action_name="paused",
        idempotency_key=idempotency_key,
        session=session,
        context=context,
        callback=social_campaigns.pause_campaign,
        request_payload={},
        event_type=social_campaigns.CAMPAIGN_PAUSE_EVENT,
    )


@router.post(
    "/webhooks/whatsapp/evolution/{integration_id}/{webhook_token}", include_in_schema=False
)
async def receive_evolution_whatsapp_webhook(
    integration_id: uuid.UUID,
    webhook_token: str,
    request: Request,
    session: Session,
) -> dict[str, int]:
    payload = await request.json()
    created = await crm_integrations.process_evolution_whatsapp_webhook(
        session,
        integration_id=integration_id,
        webhook_token=webhook_token,
        payload=payload,
    )
    await session.commit()
    return {"activitiesCreated": created}


@router.get("/action-queue", response_model=ActionQueueRead)
async def get_action_queue(
    session: Session,
    context: Annotated[
        AuthContext, Depends(require_scopes("receivables:read", "leads:read"))
    ],
    cooldown_days: Annotated[int, Query(ge=1, le=90, alias="cooldownDays")] = (
        action_queue.DEFAULT_COOLDOWN_DAYS
    ),
    limit: Annotated[int, Query(ge=1, le=action_queue.MAX_LIMIT)] = (
        action_queue.DEFAULT_LIMIT
    ),
) -> ActionQueueRead:
    """Bandeja única de candidatos a WhatsApp: cobranza vencida + prospección.

    Solo lectura y agregada: junta facturas vencidas con permiso de cobranza
    (``Receivable.collection_enabled``) y leads en etapa temprana del pipeline
    que aún no recibieron un mensaje reciente, para que el dueño del negocio
    revise y dispare el envío desde un solo lugar en vez de entrar factura por
    factura o lead por lead. El envío real sigue pasando por los endpoints ya
    existentes: ``POST /receivables/{id}/reminders`` y
    ``POST /crm/leads/{id}/messages`` (este endpoint no envía nada).

    ``cooldownDays`` (por defecto 5) excluye un candidato que ya recibió un
    recordatorio/mensaje activo dentro de esa ventana, para no repetir el
    mismo mensaje seguido.
    """
    queue = await action_queue.build_action_queue(
        session, context, cooldown_days=cooldown_days, limit=limit
    )
    return ActionQueueRead(
        collections=queue.collections,
        prospecting=queue.prospecting,
    )


@router.get("/leads", response_model=list[LeadRead])
async def get_leads(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:read"))],
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=crm.LIST_LEADS_MAX_LIMIT)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LeadRead]:
    """Lista los leads del tenant con filtros opcionales y paginación.

    Sin ``limit`` ni ``offset`` la respuesta es la de siempre, para no romper
    a quien ya consume el endpoint.
    """
    await crm.preflight_service_account_request(context, "rest.leads.list")
    leads = await crm.list_leads(
        session, context, status=status, owner_id=owner_id, limit=limit, offset=offset
    )
    return [LeadRead.model_validate(lead) for lead in leads]


@router.post("/leads", response_model=LeadRead, status_code=201)
async def post_lead(
    data: LeadCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Crea un nuevo lead vinculando a un Party existente."""
    await crm.preflight_service_account_request(context, "rest.leads.create")

    async def create() -> tuple[str, dict[str, object]]:
        entity = await crm.create_lead(session, context, data)
        return (
            str(entity.id),
            LeadRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="lead.created",
        entity_type="lead",
        callback=create,
    )


@router.post("/leads/with-party", response_model=LeadRead, status_code=201)
async def post_lead_with_party(
    data: LeadWithPartyCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Crea un lead junto con su Party asociado."""
    await crm.preflight_service_account_request(context, "rest.leads.create_with_party")

    async def create() -> tuple[str, dict[str, object]]:
        entity = await crm.create_lead_with_party(session, context, data)
        return (
            str(entity.id),
            LeadRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.create_with_party",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="lead.created_with_party",
        entity_type="lead",
        callback=create,
    )


@router.get("/leads/{lead_id}", response_model=LeadRead)
async def get_lead(
    lead_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:read"))],
) -> LeadRead:
    """Obtiene el detalle de un lead."""
    await crm.preflight_service_account_request(context, "rest.leads.get")
    entity = await crm.get_lead(session, context, lead_id)
    return LeadRead.model_validate(entity)


@router.put("/leads/{lead_id}", response_model=LeadRead)
async def put_lead(
    lead_id: uuid.UUID,
    data: LeadUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Actualiza un lead."""
    await crm.preflight_service_account_request(context, "rest.leads.update")

    async def update() -> tuple[str, dict[str, object]]:
        entity = await crm.update_lead(session, context, lead_id, data)
        return (
            str(entity.id),
            LeadRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.update",
        idempotency_key=idempotency_key,
        request_payload={
            "lead_id": str(lead_id),
            **data.model_dump(mode="json", exclude_unset=True),
        },
        action="lead.updated",
        entity_type="lead",
        callback=update,
    )


@router.put("/leads/{lead_id}/status", response_model=LeadRead)
async def put_lead_status(
    lead_id: uuid.UUID,
    data: LeadStatusUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Mueve un lead a un nuevo estado del pipeline."""
    await crm.preflight_service_account_request(context, "rest.leads.update_status")

    async def update_status() -> tuple[str, dict[str, object]]:
        entity = await crm.move_lead_status(session, context, lead_id, LeadStatus(data.new_status))
        return (
            str(entity.id),
            LeadRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.update_status",
        idempotency_key=idempotency_key,
        request_payload={
            "lead_id": str(lead_id),
            "new_status": data.new_status,
            "reason": data.reason,
        },
        action="lead.status_updated",
        entity_type="lead",
        callback=update_status,
    )


@router.put("/leads/{lead_id}/qualification", response_model=LeadRead)
async def put_lead_qualification(
    lead_id: uuid.UUID,
    data: LeadQualificationUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    await crm.preflight_service_account_request(context, "rest.leads.qualify")

    async def qualify() -> tuple[str, dict[str, object]]:
        entity = await crm.qualify_lead(session, context, lead_id, data)
        return (
            str(entity.id),
            LeadRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.qualify",
        idempotency_key=idempotency_key,
        request_payload={"lead_id": str(lead_id), **data.model_dump(mode="json")},
        action="lead.qualification_updated",
        entity_type="lead",
        callback=qualify,
    )


@router.get("/leads/{lead_id}/activities", response_model=list[LeadActivityRead])
async def get_lead_activities(
    lead_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:read"))],
) -> list[LeadActivityRead]:
    """Lista las actividades de un lead (timeline)."""
    await crm.preflight_service_account_request(context, "rest.leads.activities")
    activities = await crm.list_activities(session, context, lead_id)
    return [LeadActivityRead.model_validate(activity) for activity in activities]


@router.post("/leads/{lead_id}/messages", response_model=LeadActivityRead, status_code=201)
async def post_lead_message(
    lead_id: uuid.UUID,
    data: LeadMessageCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> dict[str, object]:
    if context.actor_type == "SERVICE_ACCOUNT":
        raise HTTPException(
            status_code=403,
            detail="Service accounts may not send lead messages",
        )

    async def send() -> tuple[str, dict[str, object]]:
        lead = await crm.get_lead(session, context, lead_id)
        if data.channel == "EMAIL":
            if not lead.party.email:
                raise HTTPException(status_code=422, detail="Lead contact has no email")
            if not data.subject:
                raise HTTPException(status_code=422, detail="Email subject is required")
            await crm_integrations.send_google_email(
                session,
                context,
                recipient=lead.party.email,
                subject=data.subject,
                message=data.message,
            )
        else:
            if not lead.party.phone:
                raise HTTPException(status_code=422, detail="Lead contact has no phone")
            await crm_integrations.send_whatsapp_message(
                session,
                context,
                recipient=lead.party.phone,
                message=data.message,
                template_id=data.template_id,
                purpose="CRM",
            )
        reminder_date = (
            datetime.now(UTC) + timedelta(days=data.follow_up_days) if data.follow_up_days else None
        )
        activity = await crm.create_activity(
            session,
            context,
            lead_id,
            LeadActivityCreate(
                lead_id=lead_id,
                activity_type=data.channel,
                subject=data.subject or "WhatsApp saliente",
                description=data.message,
                outcome="PENDING",
                reminder_date=reminder_date,
            ),
        )
        response = LeadActivityRead.model_validate(activity).model_dump(mode="json", by_alias=True)
        return str(activity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.send_message",
        idempotency_key=idempotency_key,
        request_payload={"lead_id": str(lead_id), **data.model_dump(mode="json")},
        action="lead.message_sent",
        entity_type="lead_activity",
        callback=send,
    )


@router.post("/leads/{lead_id}/activities", response_model=LeadActivityRead, status_code=201)
async def post_lead_activity(
    lead_id: uuid.UUID,
    data: LeadActivityCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Registra una nueva actividad para un lead."""
    await crm.preflight_service_account_request(context, "rest.leads.create_activity")
    canonical_data = data.model_copy(update={"lead_id": lead_id})

    async def create() -> tuple[str, dict[str, object]]:
        entity = await crm.create_activity(session, context, lead_id, canonical_data)
        return (
            str(entity.id),
            LeadActivityRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.create_activity",
        idempotency_key=idempotency_key,
        request_payload=canonical_data.model_dump(mode="json"),
        action="lead.activity_created",
        entity_type="lead_activity",
        callback=create,
    )


@router.put(
    "/leads/{lead_id}/activities/{activity_id}/reminder",
    response_model=LeadActivityRead,
)
async def put_lead_activity_reminder(
    lead_id: uuid.UUID,
    activity_id: uuid.UUID,
    data: LeadActivityReminderUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Marca el seguimiento de una actividad como hecho (o lo reabre)."""
    await crm.preflight_service_account_request(context, "rest.leads.update_reminder")

    async def update() -> tuple[str, dict[str, object]]:
        entity = await crm.set_reminder_completed(
            session, context, lead_id, activity_id, completed=data.completed
        )
        return (
            str(entity.id),
            LeadActivityRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.update_activity_reminder",
        idempotency_key=idempotency_key,
        request_payload={
            "lead_id": str(lead_id),
            "activity_id": str(activity_id),
            **data.model_dump(mode="json"),
        },
        action="lead.activity_reminder_updated",
        entity_type="lead_activity",
        callback=update,
    )


@router.post("/gmail/sync/now", response_model=GmailSyncResult)
async def post_gmail_sync_now(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("communications:write"))],
) -> GmailSyncResult:
    """Ejecuta una sincronización manual de Gmail."""
    result = await crm_integrations.sync_google_inbox(session, context)
    await session.commit()
    return result

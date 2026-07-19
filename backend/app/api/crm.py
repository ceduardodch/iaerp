import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.models.crm import LeadStatus
from app.schemas.crm import (
    GmailSyncResult,
    GoogleAuthorizationRead,
    IntegrationStatusRead,
    LeadActivityCreate,
    LeadActivityRead,
    LeadCreate,
    LeadMessageCreate,
    LeadRead,
    LeadStatusUpdate,
    LeadUpdate,
    LeadWithPartyCreate,
    WhatsAppIntegrationUpdate,
)
from app.services import crm, crm_integrations
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/crm", tags=["crm"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]


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


@router.get("/leads", response_model=list[LeadRead])
async def get_leads(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:read"))],
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> list[LeadRead]:
    """Lista todos los leads del tenant con filtros opcionales."""
    leads = await crm.list_leads(session, context, status=status, owner_id=owner_id)
    return [LeadRead.model_validate(lead) for lead in leads]


@router.post("/leads", response_model=LeadRead, status_code=201)
async def post_lead(
    data: LeadCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:write"))],
) -> dict[str, object]:
    """Crea un nuevo lead vinculando a un Party existente."""

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


@router.get("/leads/{lead_id}/activities", response_model=list[LeadActivityRead])
async def get_lead_activities(
    lead_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("leads:read"))],
) -> list[LeadActivityRead]:
    """Lista las actividades de un lead (timeline)."""
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

    async def create() -> tuple[str, dict[str, object]]:
        entity = await crm.create_activity(session, context, lead_id, data)
        return (
            str(entity.id),
            LeadActivityRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="leads.create_activity",
        idempotency_key=idempotency_key,
        request_payload={"lead_id": str(lead_id), **data.model_dump(mode="json")},
        action="lead.activity_created",
        entity_type="lead_activity",
        callback=create,
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

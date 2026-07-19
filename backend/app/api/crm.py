import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.models.crm import LeadStatus
from app.schemas.crm import (
    GmailSyncResult,
    LeadActivityCreate,
    LeadActivityRead,
    LeadCreate,
    LeadRead,
    LeadStatusUpdate,
    LeadUpdate,
    LeadWithPartyCreate,
)
from app.services import crm
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/crm", tags=["crm"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]


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
    result = await crm.sync_incoming_emails(session, context.tenant_id, uuid.UUID(context.actor_id))
    return result

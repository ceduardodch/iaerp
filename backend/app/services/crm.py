import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.crm import GmailIntegration, Lead, LeadActivity, LeadStatus
from app.models.masters import Party
from app.models.platform import User
from app.schemas.crm import (
    GmailSyncResult,
    LeadActivityCreate,
    LeadCreate,
    LeadUpdate,
    LeadWithPartyCreate,
)

# Lead Service

async def list_leads(
    session: AsyncSession,
    context: AuthContext,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
) -> list[Lead]:
    """Lista todos los leads del tenant con filtros opcionales."""
    statement = select(Lead).where(Lead.tenant_id == context.tenant_id)

    if status:
        statement = statement.where(Lead.status == status)

    if owner_id:
        statement = statement.where(Lead.owner_user_id == owner_id)

    statement = statement.order_by(Lead.created_at.desc()).limit(100)

    return list((await session.scalars(statement)).all())


async def get_lead(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
) -> Lead:
    """Obtiene un lead por ID."""
    lead = await session.scalar(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == context.tenant_id,
        )
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


async def create_lead(
    session: AsyncSession,
    context: AuthContext,
    data: LeadCreate,
) -> Lead:
    """Crea un nuevo lead vinculando a un Party existente."""
    # Verificar que el Party existe y pertenece al tenant
    party = await session.scalar(
        select(Party).where(
            Party.id == data.party_id,
            Party.tenant_id == context.tenant_id,
            Party.active.is_(True),
        )
    )
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")

    # Si se especifica owner, verificar que existe
    if data.owner_user_id:
        owner = await session.scalar(
            select(User).where(User.id == data.owner_user_id)
        )
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner user not found")

    lead = Lead(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(lead)
    await session.flush()
    return lead


async def create_lead_with_party(
    session: AsyncSession,
    context: AuthContext,
    data: LeadWithPartyCreate,
) -> Lead:
    """Crea un lead junto con su Party asociado."""
    # Crear el Party primero
    party_data = {
        "name": data.party_name,
        "identification_type": data.party_identification_type,
        "identification_number": data.party_identification_number,
        "email": data.party_email,
        "phone": data.party_phone,
        "address": data.party_address,
        "roles": ["PROSPECT"],  # Rol especial para leads
    }

    party = Party(tenant_id=context.tenant_id, **party_data)
    session.add(party)
    await session.flush()

    # Crear el lead
    lead_data = {
        "party_id": party.id,
        "status": data.status,
        "source": data.source,
        "score": data.score,
        "hotness": data.hotness,
        "estimated_value": data.estimated_value,
        "expected_close_date": data.expected_close_date,
    }

    lead = Lead(tenant_id=context.tenant_id, **lead_data)
    session.add(lead)
    await session.flush()
    return lead


async def update_lead(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    data: LeadUpdate,
) -> Lead:
    """Actualiza un lead."""
    lead = await get_lead(session, context, lead_id)

    # Actualizar solo los campos proporcionados
    update_data = data.model_dump(by_alias=False, exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)

    await session.flush()
    return lead


async def move_lead_status(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    new_status: LeadStatus,
) -> Lead:
    """Mueve un lead a un nuevo estado del pipeline."""
    lead = await get_lead(session, context, lead_id)

    # Validar transiciones válidas
    valid_transitions = {
        LeadStatus.NEW: [LeadStatus.CONTACTED, LeadStatus.LOST],
        LeadStatus.CONTACTED: [LeadStatus.QUALIFIED, LeadStatus.LOST],
        LeadStatus.QUALIFIED: [LeadStatus.PROPOSAL, LeadStatus.LOST],
        LeadStatus.PROPOSAL: [LeadStatus.NEGOTIATION, LeadStatus.LOST],
        LeadStatus.NEGOTIATION: [LeadStatus.WON, LeadStatus.LOST],
        LeadStatus.WON: [],  # Terminal
        LeadStatus.LOST: [],  # Terminal
    }

    if new_status not in valid_transitions.get(lead.status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {lead.status} to {new_status}",
        )

    lead.status = new_status

    # Si se convierte en cliente, actualizar el Party
    if new_status == LeadStatus.WON:
        party = await session.scalar(
            select(Party).where(
                Party.id == lead.party_id,
                Party.tenant_id == context.tenant_id,
            )
        )
        if party and "CUSTOMER" not in party.roles:
            party.roles = party.roles + ["CUSTOMER"]

    await session.flush()
    return lead


# LeadActivity Service

async def list_activities(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
) -> list[LeadActivity]:
    """Lista las actividades de un lead."""
    # Verificar que el lead existe
    await get_lead(session, context, lead_id)

    statement = select(LeadActivity).where(
        LeadActivity.lead_id == lead_id,
        LeadActivity.tenant_id == context.tenant_id,
    ).order_by(LeadActivity.created_at.desc()).limit(50)

    return list((await session.scalars(statement)).all())


async def create_activity(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    data: LeadActivityCreate,
) -> LeadActivity:
    """Crea una nueva actividad para un lead."""
    # Verificar que el lead existe
    await get_lead(session, context, lead_id)

    activity = LeadActivity(
        tenant_id=context.tenant_id,
        lead_id=lead_id,
        actor_id=context.actor_id,
        **data.model_dump(by_alias=False),
    )
    session.add(activity)
    await session.flush()
    return activity


async def get_pending_reminders(
    session: AsyncSession,
    from_date: datetime,
    to_date: datetime,
) -> list[LeadActivity]:
    """Obtiene recordatorios pendientes en un rango de fechas."""
    statement = select(LeadActivity).where(
        LeadActivity.reminder_date.isnot(None),
        LeadActivity.reminder_completed.is_(False),
        LeadActivity.reminder_date >= from_date,
        LeadActivity.reminder_date <= to_date,
    ).order_by(LeadActivity.reminder_date)

    return list((await session.scalars(statement)).all())


# Gmail Integration Service

async def get_gmail_integration(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GmailIntegration | None:
    """Obtiene la integración Gmail de un usuario."""
    return cast(
        GmailIntegration | None,
        await session.scalar(
            select(GmailIntegration).where(
                GmailIntegration.tenant_id == tenant_id,
                GmailIntegration.user_id == user_id,
                GmailIntegration.active.is_(True),
            )
        ),
    )


async def sync_incoming_emails(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GmailSyncResult:
    """Sincroniza emails entrantes desde Gmail a actividades de lead.

    Esta función es un placeholder para la implementación real.
    Por ahora devuelve un resultado vacío.
    """
    integration = await get_gmail_integration(session, tenant_id, user_id)
    if not integration or not integration.sync_enabled:
        return GmailSyncResult(
            messages_processed=0,
            activities_created=0,
            leads_matched=0,
            errors=["Gmail integration not enabled"],
            last_sync_at=datetime.now(UTC),
        )

    # TODO: Implementar sincronización real con Gmail API
    # Por ahora, actualizar last_sync_at
    integration.last_sync_at = datetime.now(UTC)
    await session.flush()

    return GmailSyncResult(
        messages_processed=0,
        activities_created=0,
        leads_matched=0,
        errors=[],
        last_sync_at=datetime.now(UTC),
    )


async def find_lead_by_email(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
) -> Lead | None:
    """Busca un lead por el email de su Party asociado."""
    # Buscar el Party por email
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == tenant_id,
            Party.email == email,
            Party.active.is_(True),
        )
    )

    if not party:
        return None

    # Buscar el lead asociado
    return cast(
        Lead | None,
        await session.scalar(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.party_id == party.id,
            )
        ),
    )

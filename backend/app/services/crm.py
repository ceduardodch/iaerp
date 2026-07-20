import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.crm import Lead, LeadActivity, LeadStatus
from app.models.masters import Party, Product
from app.models.platform import User
from app.schemas.crm import LeadActivityCreate, LeadCreate, LeadUpdate, LeadWithPartyCreate

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
        owner = await session.scalar(select(User).where(User.id == data.owner_user_id))
        if owner is None:
            raise HTTPException(status_code=404, detail="Owner user not found")

    if data.product_id is not None:
        product = await session.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.tenant_id == context.tenant_id,
                Product.active.is_(True),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
    lead_data = data.model_dump(by_alias=False)
    if lead_data["owner_user_id"] is None and context.actor_type == "USER":
        lead_data["owner_user_id"] = uuid.UUID(context.actor_id)
    lead = Lead(tenant_id=context.tenant_id, **lead_data)
    session.add(lead)
    await session.flush()
    await session.refresh(lead, attribute_names=["party", "product", "owner"])
    return lead


async def create_lead_with_party(
    session: AsyncSession,
    context: AuthContext,
    data: LeadWithPartyCreate,
) -> Lead:
    """Crea un lead junto con su Party asociado."""
    # Crear el Party primero
    party_data: dict[str, object] = {
        "name": data.party_name,
        "identification_type": data.party_identification_type,
        "identification_number": data.party_identification_number,
        "email": data.party_email,
        "phone": data.party_phone,
        "address": data.party_address,
        "roles": [],
    }

    party = Party(tenant_id=context.tenant_id, **party_data)
    session.add(party)
    await session.flush()

    if data.product_id is not None:
        product = await session.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.tenant_id == context.tenant_id,
                Product.active.is_(True),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

    # Crear el lead
    lead_data = {
        "party_id": party.id,
        "title": data.title,
        "product_id": data.product_id,
        "status": data.status,
        "source": data.source,
        "score": data.score,
        "hotness": data.hotness,
        "estimated_value": data.estimated_value,
        "expected_close_date": data.expected_close_date,
        "owner_user_id": data.owner_user_id,
    }
    if lead_data["owner_user_id"] is None and context.actor_type == "USER":
        lead_data["owner_user_id"] = uuid.UUID(context.actor_id)

    lead = Lead(tenant_id=context.tenant_id, **lead_data)
    session.add(lead)
    await session.flush()
    await session.refresh(lead, attribute_names=["party", "product", "owner"])
    return lead


async def update_lead(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    data: LeadUpdate,
) -> Lead:
    """Actualiza un lead."""
    lead = await get_lead(session, context, lead_id)

    if data.product_id is not None:
        product = await session.scalar(
            select(Product).where(
                Product.id == data.product_id,
                Product.tenant_id == context.tenant_id,
                Product.active.is_(True),
            )
        )
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")

    # Actualizar solo los campos proporcionados
    update_data = data.model_dump(by_alias=False, exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)

    await session.flush()
    await session.refresh(lead, attribute_names=["updated_at", "party", "product", "owner"])
    return lead


async def move_lead_status(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    new_status: LeadStatus,
) -> Lead:
    """Mueve un lead a un nuevo estado del pipeline."""
    lead = await get_lead(session, context, lead_id)

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
    await session.refresh(lead, attribute_names=["updated_at", "party", "product", "owner"])
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

    statement = (
        select(LeadActivity)
        .where(
            LeadActivity.lead_id == lead_id,
            LeadActivity.tenant_id == context.tenant_id,
        )
        .order_by(LeadActivity.created_at.desc())
        .limit(50)
    )

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

    # lead_id se excluye del dump: el path es la fuente de verdad y dejarlo
    # duplicado provocaba TypeError (kwarg repetido) -> 500 en el endpoint.
    activity = LeadActivity(
        tenant_id=context.tenant_id,
        lead_id=lead_id,
        actor_id=context.actor_id,
        **data.model_dump(by_alias=False, exclude={"lead_id"}),
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
    statement = (
        select(LeadActivity)
        .where(
            LeadActivity.reminder_date.isnot(None),
            LeadActivity.reminder_completed.is_(False),
            LeadActivity.reminder_date >= from_date,
            LeadActivity.reminder_date <= to_date,
        )
        .order_by(LeadActivity.reminder_date)
    )

    return list((await session.scalars(statement)).all())

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.crm import (
    Lead,
    LeadActivity,
    LeadCampaignTouch,
    LeadStatus,
    SocialCampaignVariant,
)
from app.models.masters import Party, Product
from app.models.platform import User
from app.schemas.crm import (
    LeadActivityCreate,
    LeadCampaignCaptureCreate,
    LeadCreate,
    LeadQualificationUpdate,
    LeadUpdate,
    LeadWithPartyCreate,
)

# Lead Service


LIST_LEADS_MAX_LIMIT = 200


async def list_leads(
    session: AsyncSession,
    context: AuthContext,
    status: str | None = None,
    owner_id: uuid.UUID | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Lead]:
    """Lista los leads del tenant con filtros opcionales y paginación.

    Antes devolvía como mucho 100 sin forma de pedir el resto, así que el
    kanban ocultaba el pipeline a partir de ese punto y el cargador de
    prospectos no podía deduplicar por RUC más allá de los 100 más recientes.
    """
    statement = select(Lead).where(Lead.tenant_id == context.tenant_id)

    if status:
        statement = statement.where(Lead.status == status)

    if owner_id:
        statement = statement.where(Lead.owner_user_id == owner_id)

    # ``created_at`` solo no basta para paginar: dos leads creados en el mismo
    # instante —lo normal en una carga masiva— pueden ordenarse distinto entre
    # una consulta y la siguiente, repitiendo o saltando filas. El id desempata.
    statement = (
        statement.order_by(Lead.created_at.desc(), Lead.id.desc())
        .offset(offset)
        .limit(min(limit, LIST_LEADS_MAX_LIMIT))
    )

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


async def capture_campaign_lead(
    session: AsyncSession,
    context: AuthContext,
    data: LeadCampaignCaptureCreate,
) -> tuple[Lead, bool, Literal["SOURCE_REFERENCE", "CONTACT"] | None]:
    """Ingiere un lead de redes sin inventar una identidad tributaria.

    La referencia externa del proveedor es la primera barrera contra
    duplicados. Si no existe, email o teléfono permiten reutilizar el último
    lead del mismo tenant, dejando intacta su atribución original.
    """
    if data.campaign_variant_id is not None:
        variant = await session.scalar(
            select(SocialCampaignVariant.id).where(
                SocialCampaignVariant.tenant_id == context.tenant_id,
                SocialCampaignVariant.id == data.campaign_variant_id,
            )
        )
        if variant is None:
            raise HTTPException(
                status_code=422,
                detail="Campaign variant does not belong to tenant",
            )

    touched_lead = await session.scalar(
        select(Lead)
        .join(
            LeadCampaignTouch,
            LeadCampaignTouch.lead_id == Lead.id,
        )
        .where(
            LeadCampaignTouch.tenant_id == context.tenant_id,
            LeadCampaignTouch.source == data.source,
            LeadCampaignTouch.source_external_id == data.source_external_id,
            Lead.tenant_id == context.tenant_id,
        )
    )
    if touched_lead is not None:
        return touched_lead, False, "SOURCE_REFERENCE"

    existing = await session.scalar(
        select(Lead).where(
            Lead.tenant_id == context.tenant_id,
            Lead.source == data.source,
            Lead.source_external_id == data.source_external_id,
        )
    )
    if existing is not None:
        session.add(_campaign_touch(context, data, existing.id))
        await session.flush()
        return existing, False, "SOURCE_REFERENCE"

    contact_filters = []
    if data.party_email:
        contact_filters.append(func.lower(Party.email) == data.party_email.lower())
    if data.party_phone:
        contact_filters.append(Party.phone == data.party_phone)
    if contact_filters:
        duplicate = await session.scalar(
            select(Lead)
            .join(Party, Party.id == Lead.party_id)
            .where(Lead.tenant_id == context.tenant_id, or_(*contact_filters))
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
        if duplicate is not None:
            session.add(_campaign_touch(context, data, duplicate.id))
            campaign_label = data.campaign_name or data.campaign_id or "sin nombre"
            session.add(
                LeadActivity(
                    tenant_id=context.tenant_id,
                    lead_id=duplicate.id,
                    actor_id=context.actor_id,
                    activity_type="NOTE",
                    subject="Nueva respuesta de campaña",
                    description=f"Origen: {data.source}. Campaña: {campaign_label}.",
                    outcome="PENDING",
                    reminder_date=None,
                    reminder_completed=False,
                )
            )
            await session.flush()
            return duplicate, False, "CONTACT"

    placeholder = hashlib.sha256(f"{data.source}:{data.source_external_id}".encode()).hexdigest()[
        :20
    ]
    party = Party(
        tenant_id=context.tenant_id,
        name=data.party_name,
        identification_type="FINAL_CONSUMER",
        identification_number=f"lead-{placeholder}",
        roles=[],
        email=data.party_email,
        phone=data.party_phone,
        address=None,
    )
    session.add(party)
    await session.flush()

    lead = Lead(
        tenant_id=context.tenant_id,
        party_id=party.id,
        title=data.title,
        status=LeadStatus.NEW,
        source=data.source,
        source_external_id=data.source_external_id,
        campaign_id=data.campaign_id,
        campaign_name=data.campaign_name,
        ad_id=data.ad_id,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        utm_content=data.utm_content,
        consent_captured_at=data.consent_captured_at,
        consent_text_version=data.consent_text_version,
        campaign_variant_id=data.campaign_variant_id,
        qualification_status="UNREVIEWED",
        qualified_at=None,
        qualified_by=None,
        company_name=data.company_name,
        job_title=data.job_title,
        uses_aws=data.uses_aws,
        decision_authority=data.decision_authority,
        qualification_reason=None,
        owner_user_id=uuid.UUID(context.actor_id) if context.actor_type == "USER" else None,
        score=0,
        hotness="COLD",
        estimated_value=None,
        expected_close_date=None,
    )
    session.add(lead)
    await session.flush()
    session.add(_campaign_touch(context, data, lead.id))
    campaign_label = data.campaign_name or data.campaign_id or "sin nombre"
    session.add(
        LeadActivity(
            tenant_id=context.tenant_id,
            lead_id=lead.id,
            actor_id=context.actor_id,
            activity_type="NOTE",
            subject="Lead captado por campaña",
            description=f"Origen: {data.source}. Campaña: {campaign_label}.",
            outcome="PENDING",
            reminder_date=None,
            reminder_completed=False,
        )
    )
    await session.flush()
    await session.refresh(lead, attribute_names=["party", "product", "owner"])
    return lead, True, None


def _campaign_touch(
    context: AuthContext,
    data: LeadCampaignCaptureCreate,
    lead_id: uuid.UUID,
) -> LeadCampaignTouch:
    return LeadCampaignTouch(
        tenant_id=context.tenant_id,
        lead_id=lead_id,
        source=data.source,
        source_external_id=data.source_external_id,
        campaign_id=data.campaign_id,
        campaign_name=data.campaign_name,
        ad_id=data.ad_id,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        utm_content=data.utm_content,
        consent_captured_at=data.consent_captured_at,
        consent_text_version=data.consent_text_version,
    )


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
        if party and party.identification_number.startswith("lead-"):
            raise HTTPException(
                status_code=422,
                detail="Complete the prospect fiscal identity before converting it to a customer",
            )
        if party and "CUSTOMER" not in party.roles:
            party.roles = party.roles + ["CUSTOMER"]

    await session.flush()
    await session.refresh(lead, attribute_names=["updated_at", "party", "product", "owner"])
    return lead


async def qualify_lead(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    data: LeadQualificationUpdate,
) -> Lead:
    """Registra una decisión humana de calificación con evidencia mínima."""
    lead = await get_lead(session, context, lead_id)
    lead.qualification_status = data.status
    lead.company_name = data.company_name
    lead.job_title = data.job_title
    lead.uses_aws = data.uses_aws
    lead.decision_authority = data.decision_authority
    lead.qualification_reason = data.reason
    lead.qualified_at = datetime.now(UTC)
    lead.qualified_by = context.actor_id
    session.add(
        LeadActivity(
            tenant_id=context.tenant_id,
            lead_id=lead.id,
            actor_id=context.actor_id,
            activity_type="NOTE",
            subject=("Lead calificado" if data.status == "QUALIFIED" else "Lead descartado"),
            description=data.reason,
            outcome="POSITIVE" if data.status == "QUALIFIED" else "NEGATIVE",
            reminder_date=None,
            reminder_completed=False,
        )
    )
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


async def set_reminder_completed(
    session: AsyncSession,
    context: AuthContext,
    lead_id: uuid.UUID,
    activity_id: uuid.UUID,
    *,
    completed: bool,
) -> LeadActivity:
    """Cierra o reabre el seguimiento de una actividad del lead."""
    # El lead se valida primero para que un activity_id de otro tenant no se
    # distinga de uno inexistente.
    await get_lead(session, context, lead_id)
    statement = select(LeadActivity).where(
        LeadActivity.id == activity_id,
        LeadActivity.lead_id == lead_id,
        LeadActivity.tenant_id == context.tenant_id,
    )
    activity = await session.scalar(statement)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    if activity.reminder_date is None:
        raise HTTPException(status_code=422, detail="Activity has no reminder to close")
    activity.reminder_completed = completed
    await session.flush()
    # ``updated_at`` lo calcula la base: sin refrescarlo, serializar la
    # respuesta dispara IO perezoso fuera del contexto async.
    await session.refresh(activity, attribute_names=["updated_at"])
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

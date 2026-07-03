import secrets
import uuid
from datetime import UTC, datetime
from hashlib import scrypt

from fastapi import HTTPException
from sqlalchemy import cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.masters import EmissionPoint, Establishment, Party, Product, Tag, TaxCategory
from app.models.platform import AutomationSettings, ServiceAccount, Tenant
from app.schemas.masters import (
    EmissionPointCreate,
    EstablishmentCreate,
    PartyCreate,
    ProductCreate,
    TagCreate,
)
from app.schemas.platform import AutomationSettingsUpdate, ServiceAccountCreate
from app.services.identity import (
    delete_service_account,
    disable_service_account,
    provision_service_account,
)


async def get_active_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.active.is_(True))
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


async def list_establishments(
    session: AsyncSession,
    context: AuthContext,
) -> list[Establishment]:
    return list(
        (
            await session.scalars(
                select(Establishment)
                .where(
                    Establishment.tenant_id == context.tenant_id,
                    Establishment.active.is_(True),
                )
                .order_by(Establishment.code)
            )
        ).all()
    )


async def create_establishment(
    session: AsyncSession,
    context: AuthContext,
    data: EstablishmentCreate,
) -> Establishment:
    entity = Establishment(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def list_emission_points(
    session: AsyncSession,
    context: AuthContext,
) -> list[EmissionPoint]:
    return list(
        (
            await session.scalars(
                select(EmissionPoint)
                .where(
                    EmissionPoint.tenant_id == context.tenant_id,
                    EmissionPoint.active.is_(True),
                )
                .order_by(EmissionPoint.code)
            )
        ).all()
    )


async def create_emission_point(
    session: AsyncSession,
    context: AuthContext,
    data: EmissionPointCreate,
) -> EmissionPoint:
    establishment = await session.scalar(
        select(Establishment.id).where(
            Establishment.id == data.establishment_id,
            Establishment.tenant_id == context.tenant_id,
            Establishment.active.is_(True),
        )
    )
    if establishment is None:
        raise HTTPException(status_code=404, detail="Establishment not found")
    entity = EmissionPoint(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def list_tax_categories(
    session: AsyncSession,
    context: AuthContext,
) -> list[TaxCategory]:
    return list(
        (
            await session.scalars(
                select(TaxCategory)
                .where(
                    TaxCategory.tenant_id == context.tenant_id,
                    TaxCategory.active.is_(True),
                )
                .order_by(TaxCategory.sri_code)
            )
        ).all()
    )


async def list_tags(session: AsyncSession, context: AuthContext) -> list[Tag]:
    return list(
        (
            await session.scalars(
                select(Tag)
                .where(Tag.tenant_id == context.tenant_id, Tag.active.is_(True))
                .order_by(Tag.name)
            )
        ).all()
    )


async def create_tag(session: AsyncSession, context: AuthContext, data: TagCreate) -> Tag:
    entity = Tag(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def search_parties(
    session: AsyncSession,
    context: AuthContext,
    query: str | None,
    role: str | None,
) -> list[Party]:
    statement = select(Party).where(
        Party.tenant_id == context.tenant_id,
        Party.active.is_(True),
    )
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Party.name.ilike(pattern),
                Party.identification_number.ilike(pattern),
            )
        )
    if role:
        bind = session.get_bind()
        role_filter = (
            cast(Party.roles, JSONB).contains([role])
            if bind.dialect.name == "postgresql"
            else Party.roles.contains([role])
        )
        statement = statement.where(role_filter)
    return list((await session.scalars(statement.order_by(Party.name).limit(100))).all())


async def create_party(
    session: AsyncSession,
    context: AuthContext,
    data: PartyCreate,
) -> Party:
    entity = Party(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def update_party(
    session: AsyncSession,
    context: AuthContext,
    party_id: uuid.UUID,
    data: PartyCreate,
) -> Party:
    entity = await session.scalar(
        select(Party).where(
            Party.id == party_id,
            Party.tenant_id == context.tenant_id,
            Party.active.is_(True),
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Party not found")
    for field, value in data.model_dump(by_alias=False).items():
        setattr(entity, field, value)
    await session.flush()
    return entity


async def search_products(
    session: AsyncSession,
    context: AuthContext,
    query: str | None,
) -> list[Product]:
    statement = select(Product).where(
        Product.tenant_id == context.tenant_id,
        Product.active.is_(True),
    )
    if query:
        pattern = f"%{query}%"
        statement = statement.where(or_(Product.name.ilike(pattern), Product.code.ilike(pattern)))
    return list((await session.scalars(statement.order_by(Product.name).limit(100))).all())


async def create_product(
    session: AsyncSession,
    context: AuthContext,
    data: ProductCreate,
) -> Product:
    tax_category = await session.scalar(
        select(TaxCategory.id).where(
            TaxCategory.id == data.tax_category_id,
            TaxCategory.tenant_id == context.tenant_id,
            TaxCategory.active.is_(True),
        )
    )
    if tax_category is None:
        raise HTTPException(status_code=404, detail="Tax category not found")
    entity = Product(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def update_product(
    session: AsyncSession,
    context: AuthContext,
    product_id: uuid.UUID,
    data: ProductCreate,
) -> Product:
    entity = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == context.tenant_id,
            Product.active.is_(True),
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Product not found")
    tax_category = await session.scalar(
        select(TaxCategory.id).where(
            TaxCategory.id == data.tax_category_id,
            TaxCategory.tenant_id == context.tenant_id,
            TaxCategory.active.is_(True),
        )
    )
    if tax_category is None:
        raise HTTPException(status_code=404, detail="Tax category not found")
    for field, value in data.model_dump(by_alias=False).items():
        setattr(entity, field, value)
    await session.flush()
    return entity


async def get_automation_settings(
    session: AsyncSession,
    context: AuthContext,
) -> AutomationSettings:
    entity = await session.get(AutomationSettings, context.tenant_id)
    if entity is None:
        entity = AutomationSettings(tenant_id=context.tenant_id)
        session.add(entity)
        await session.flush()
    return entity


async def update_automation_settings(
    session: AsyncSession,
    context: AuthContext,
    data: AutomationSettingsUpdate,
) -> AutomationSettings:
    entity = await get_automation_settings(session, context)
    entity.writes_enabled = data.writes_enabled
    entity.daily_amount_limit = data.daily_amount_limit
    await session.flush()
    await session.refresh(entity)
    return entity


def _hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


async def list_service_accounts(
    session: AsyncSession,
    context: AuthContext,
) -> list[ServiceAccount]:
    return list(
        (
            await session.scalars(
                select(ServiceAccount)
                .where(ServiceAccount.tenant_id == context.tenant_id)
                .order_by(ServiceAccount.name)
            )
        ).all()
    )


async def create_service_account(
    session: AsyncSession,
    context: AuthContext,
    data: ServiceAccountCreate,
) -> tuple[ServiceAccount, str]:
    if data.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="expiresAt must be in the future")
    client_secret = secrets.token_urlsafe(36)
    client_id = f"iaerp-{context.tenant_id.hex[:8]}-{secrets.token_hex(6)}"
    await provision_service_account(
        client_id=client_id,
        client_secret=client_secret,
        name=data.name,
        scopes=data.scopes,
    )
    entity = ServiceAccount(
        tenant_id=context.tenant_id,
        client_id=client_id,
        name=data.name,
        scopes=sorted(set(data.scopes)),
        secret_hash=_hash_secret(client_secret),
        expires_at=data.expires_at,
    )
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError:
        await delete_service_account(client_id)
        raise
    return entity, client_secret


async def revoke_service_account(
    session: AsyncSession,
    context: AuthContext,
    account_id: uuid.UUID,
) -> ServiceAccount:
    entity = await session.scalar(
        select(ServiceAccount).where(
            ServiceAccount.id == account_id,
            ServiceAccount.tenant_id == context.tenant_id,
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    if entity.active:
        await disable_service_account(entity.client_id)
        entity.active = False
        await session.flush()
    return entity

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, create_dev_token, require_scopes
from app.core.config import get_settings
from app.db.session import get_session
from app.models.platform import (
    AutomationSettings,
    Membership,
    OperationRecord,
    Tenant,
    User,
)
from app.schemas.masters import (
    EmissionPointCreate,
    EmissionPointRead,
    EstablishmentCreate,
    EstablishmentRead,
    PartyCreate,
    PartyRead,
    ProductCreate,
    ProductRead,
    TagCreate,
    TagRead,
    TaxCategoryRead,
)
from app.schemas.platform import (
    AutomationSettingsRead,
    AutomationSettingsUpdate,
    DevTokenRequest,
    MembershipRead,
    OperationRead,
    ServiceAccountCreate,
    ServiceAccountCreated,
    ServiceAccountRead,
    TenantContextRead,
    TokenResponse,
)
from app.services import masters
from app.services.unit_of_work import execute_idempotent

router = APIRouter()
settings = get_settings()

ALL_DEV_SCOPES = {
    "context:read",
    "memberships:read",
    "service-accounts:read",
    "service-accounts:write",
    "organization:read",
    "organization:write",
    "tags:read",
    "tags:write",
    "automation:read",
    "automation:write",
    "operations:read",
    "parties:read",
    "parties:write",
    "products:read",
    "products:write",
}

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/dev/token", response_model=TokenResponse, include_in_schema=False)
async def issue_dev_token(data: DevTokenRequest, session: Session) -> TokenResponse:
    if settings.AUTH_MODE != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    row = await session.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.email == data.email,
            User.active.is_(True),
            Membership.tenant_id == data.tenant_id,
            Membership.active.is_(True),
        )
    )
    result = row.first()
    if result is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    user, membership = result
    requested = set(data.scopes) if data.scopes else ALL_DEV_SCOPES
    if not requested.issubset(ALL_DEV_SCOPES):
        raise HTTPException(status_code=403, detail="Unsupported development scope")
    token, expires_in = create_dev_token(
        subject=user.external_subject,
        tenant_id=data.tenant_id,
        roles=membership.roles,
        scopes=sorted(requested),
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/context", response_model=TenantContextRead)
async def get_context(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("context:read"))],
) -> TenantContextRead:
    tenant = await masters.get_active_tenant(session, context.tenant_id)
    automation = await session.get(AutomationSettings, context.tenant_id)
    return TenantContextRead(
        tenant_id=tenant.id,
        ruc=tenant.ruc,
        name=tenant.name,
        roles=sorted(context.roles),
        scopes=sorted(context.scopes),
        automation_writes_enabled=automation.writes_enabled if automation else False,
    )


@router.get("/memberships", response_model=list[MembershipRead])
async def list_memberships(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("memberships:read"))],
) -> list[MembershipRead]:
    if context.actor_type != "USER":
        raise HTTPException(status_code=403, detail="Only users have memberships")
    rows = await session.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.user_id == uuid.UUID(context.actor_id),
            Tenant.active.is_(True),
        )
        .order_by(Tenant.name)
    )
    return [
        MembershipRead(
            tenant_id=tenant.id,
            organization_id=tenant.organization_id,
            ruc=tenant.ruc,
            tenant_name=tenant.name,
            roles=membership.roles,
            active=membership.active,
        )
        for membership, tenant in rows.all()
    ]


@router.get("/service-accounts", response_model=list[ServiceAccountRead])
async def get_service_accounts(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("service-accounts:read"))],
) -> list[ServiceAccountRead]:
    entities = await masters.list_service_accounts(session, context)
    return [ServiceAccountRead.model_validate(entity) for entity in entities]


@router.post("/service-accounts", response_model=ServiceAccountCreated, status_code=201)
async def post_service_account(
    data: ServiceAccountCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("service-accounts:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity, secret = await masters.create_service_account(session, context, data)
        response = ServiceAccountCreated(
            account=ServiceAccountRead.model_validate(entity),
            client_secret=secret,
        ).model_dump(mode="json", by_alias=True)
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="service_accounts.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="service_account.created",
        entity_type="service_account",
        callback=create,
    )


@router.delete("/service-accounts/{account_id}", response_model=ServiceAccountRead)
async def delete_service_account(
    account_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("service-accounts:write"))],
) -> dict[str, object]:
    async def revoke() -> tuple[str, dict[str, object]]:
        entity = await masters.revoke_service_account(session, context, account_id)
        return (
            str(entity.id),
            ServiceAccountRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="service_accounts.revoke",
        idempotency_key=idempotency_key,
        request_payload={"account_id": str(account_id)},
        action="service_account.revoked",
        entity_type="service_account",
        callback=revoke,
    )


@router.get("/establishments", response_model=list[EstablishmentRead])
async def get_establishments(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:read"))],
) -> list[EstablishmentRead]:
    return [
        EstablishmentRead.model_validate(entity)
        for entity in await masters.list_establishments(session, context)
    ]


@router.post("/establishments", response_model=EstablishmentRead, status_code=201)
async def post_establishment(
    data: EstablishmentCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_establishment(session, context, data)
        return (
            str(entity.id),
            EstablishmentRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="establishments.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="establishment.created",
        entity_type="establishment",
        callback=create,
    )


@router.get("/emission-points", response_model=list[EmissionPointRead])
async def get_emission_points(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:read"))],
) -> list[EmissionPointRead]:
    return [
        EmissionPointRead.model_validate(entity)
        for entity in await masters.list_emission_points(session, context)
    ]


@router.post("/emission-points", response_model=EmissionPointRead, status_code=201)
async def post_emission_point(
    data: EmissionPointCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_emission_point(session, context, data)
        return (
            str(entity.id),
            EmissionPointRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="emission_points.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="emission_point.created",
        entity_type="emission_point",
        callback=create,
    )


@router.get("/tax-categories", response_model=list[TaxCategoryRead])
async def get_tax_categories(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:read"))],
) -> list[TaxCategoryRead]:
    return [
        TaxCategoryRead.model_validate(entity)
        for entity in await masters.list_tax_categories(session, context)
    ]


@router.get("/tags", response_model=list[TagRead])
async def get_tags(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tags:read"))],
) -> list[TagRead]:
    return [TagRead.model_validate(entity) for entity in await masters.list_tags(session, context)]


@router.post("/tags", response_model=TagRead, status_code=201)
async def post_tag(
    data: TagCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tags:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_tag(session, context, data)
        return (
            str(entity.id),
            TagRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="tags.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="tag.created",
        entity_type="tag",
        callback=create,
    )


@router.get("/parties", response_model=list[PartyRead])
async def get_parties(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("parties:read"))],
    q: Annotated[str | None, Query(min_length=2)] = None,
    role: str | None = None,
) -> list[PartyRead]:
    return [
        PartyRead.model_validate(entity)
        for entity in await masters.search_parties(session, context, q, role)
    ]


@router.post("/parties", response_model=PartyRead, status_code=201)
async def post_party(
    data: PartyCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("parties:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_party(session, context, data)
        return (
            str(entity.id),
            PartyRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="parties.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="party.created",
        entity_type="party",
        callback=create,
    )


@router.put("/parties/{party_id}", response_model=PartyRead)
async def put_party(
    party_id: uuid.UUID,
    data: PartyCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("parties:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await masters.update_party(session, context, party_id, data)
        return (
            str(entity.id),
            PartyRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="parties.update",
        idempotency_key=idempotency_key,
        request_payload={"party_id": str(party_id), **data.model_dump(mode="json")},
        action="party.updated",
        entity_type="party",
        callback=update,
    )


@router.get("/products", response_model=list[ProductRead])
async def get_products(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("products:read"))],
    q: str | None = None,
) -> list[ProductRead]:
    return [
        ProductRead.model_validate(entity)
        for entity in await masters.search_products(session, context, q)
    ]


@router.post("/products", response_model=ProductRead, status_code=201)
async def post_product(
    data: ProductCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("products:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_product(session, context, data)
        return (
            str(entity.id),
            ProductRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="products.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="product.created",
        entity_type="product",
        callback=create,
    )


@router.put("/products/{product_id}", response_model=ProductRead)
async def put_product(
    product_id: uuid.UUID,
    data: ProductCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("products:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await masters.update_product(session, context, product_id, data)
        return (
            str(entity.id),
            ProductRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="products.update",
        idempotency_key=idempotency_key,
        request_payload={"product_id": str(product_id), **data.model_dump(mode="json")},
        action="product.updated",
        entity_type="product",
        callback=update,
    )


@router.get("/automation/settings", response_model=AutomationSettingsRead)
async def get_automation(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("automation:read"))],
) -> AutomationSettingsRead:
    entity = await masters.get_automation_settings(session, context)
    return AutomationSettingsRead.model_validate(entity)


@router.put("/automation/settings", response_model=AutomationSettingsRead)
async def put_automation(
    data: AutomationSettingsUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("automation:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await masters.update_automation_settings(session, context, data)
        return (
            str(context.tenant_id),
            AutomationSettingsRead.model_validate(entity).model_dump(
                mode="json",
                by_alias=True,
            ),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="automation_settings.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="automation_settings.updated",
        entity_type="automation_settings",
        callback=update,
    )


@router.get("/operations/{operation_id}", response_model=OperationRead)
async def get_operation(
    operation_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("operations:read"))],
) -> OperationRead:
    entity = await session.scalar(
        select(OperationRecord).where(
            OperationRecord.id == operation_id,
            OperationRecord.tenant_id == context.tenant_id,
        )
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return OperationRead(
        operation_id=entity.id,
        status=entity.status,
        correlation_id=entity.correlation_id,
        created_at=entity.created_at,
        expires_at=entity.expires_at,
        result=entity.result,
        error=entity.error,
    )

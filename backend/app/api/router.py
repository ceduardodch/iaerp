import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, create_dev_token, require_scopes
from app.core.config import get_settings
from app.db.session import get_session
from app.models.billing import SalesDocument
from app.models.platform import (
    AutomationSettings,
    Membership,
    OperationRecord,
    Tenant,
    User,
)
from app.models.receivables import CollectionPolicy
from app.schemas.billing import (
    ArtifactDownloadRead,
    CreditNoteInput,
    DocumentArtifactRead,
    InvoiceInput,
    InvoicePreviewInput,
    InvoicePreviewRead,
    SalesDocumentRead,
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
    FiscalSettingsRead,
    FiscalSettingsUpdate,
    MembershipRead,
    OperationRead,
    OrganizationProfileRead,
    OrganizationProfileUpdate,
    ServiceAccountCreate,
    ServiceAccountCreated,
    ServiceAccountRead,
    TenantContextRead,
    TokenResponse,
)
from app.schemas.receivables import (
    AccountItemRead,
    AgingBucketTotalRead,
    AgingSummaryRead,
    CollectionPolicyRead,
    CollectionPolicyUpdate,
    MovementRead,
    PartyAgingBucketTotalRead,
    PaymentInput,
    ReminderInput,
    ReminderRead,
    ReversalInput,
)
from app.services import billing, fiscal_settings, masters, receivables
from app.services.unit_of_work import append_audit, execute_idempotent

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
    "invoices:read",
    "invoices:write",
    "invoices:issue",
    "credit-notes:issue",
    "receivables:read",
    "receivables:write",
    "receivables:notify",
    "leads:read",
    "leads:write",
    "communications:read",
    "communications:write",
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
        default_payment_terms_days=tenant.default_payment_terms_days,
    )


@router.put("/organization/profile", response_model=OrganizationProfileRead)
async def put_organization_profile(
    data: OrganizationProfileUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        tenant = await masters.get_active_tenant(session, context.tenant_id)
        if tenant.ruc != data.ruc:
            issued = await session.scalar(
                select(SalesDocument.id)
                .where(
                    SalesDocument.tenant_id == context.tenant_id,
                    SalesDocument.status != "DRAFT",
                )
                .limit(1)
            )
            if issued is not None:
                raise HTTPException(
                    status_code=409,
                    detail="RUC cannot change after a fiscal document has been issued",
                )
        tenant.name = data.name
        tenant.ruc = data.ruc
        tenant.default_payment_terms_days = data.default_payment_terms_days
        await session.flush()
        response = OrganizationProfileRead(
            tenant_id=tenant.id,
            name=tenant.name,
            ruc=tenant.ruc,
            default_payment_terms_days=tenant.default_payment_terms_days,
        ).model_dump(mode="json", by_alias=True)
        return str(tenant.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="organization.profile.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="organization.profile.updated",
        entity_type="tenant",
        callback=update,
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


@router.get("/organization/fiscal-settings", response_model=FiscalSettingsRead)
async def get_fiscal_settings(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:read"))],
) -> FiscalSettingsRead:
    return await fiscal_settings.read_settings(session, context)


@router.put("/organization/fiscal-settings", response_model=FiscalSettingsRead)
async def put_fiscal_settings(
    data: FiscalSettingsUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        response = await fiscal_settings.update_settings(session, context, data)
        return str(context.tenant_id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="organization.fiscal_settings.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="organization.fiscal_settings.updated",
        entity_type="tenant_fiscal_settings",
        callback=update,
    )


@router.post("/organization/signing-certificate", response_model=FiscalSettingsRead)
async def post_signing_certificate(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
    file: Annotated[UploadFile, File()],
    password: Annotated[str, Form(min_length=1, max_length=500)],
) -> dict[str, object]:
    certificate_bytes = await file.read(fiscal_settings.MAX_CERTIFICATE_SIZE + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        response = await fiscal_settings.upload_signing_certificate(
            session,
            context,
            filename=file.filename,
            data=certificate_bytes,
            password=password,
        )
        return str(context.tenant_id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="organization.signing_certificate.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "filename": file.filename,
            "sha256": hashlib.sha256(certificate_bytes).hexdigest(),
        },
        action="organization.signing_certificate.uploaded",
        entity_type="tenant_fiscal_settings",
        callback=upload,
    )


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


@router.post("/invoices/preview", response_model=InvoicePreviewRead)
async def post_invoice_preview(
    data: InvoicePreviewInput,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
) -> InvoicePreviewRead:
    return await billing.preview_invoice(session, context, data)


@router.post("/invoices", response_model=SalesDocumentRead, status_code=201)
async def post_invoice(
    data: InvoiceInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await billing.create_invoice_draft(session, context, data)
        response_model = await billing.to_sales_document_read(session, context, entity)
        return (
            str(entity.id),
            response_model.model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.create_draft",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="invoice.draft_created",
        entity_type="sales_document",
        callback=create,
    )


@router.get("/invoices", response_model=list[SalesDocumentRead])
async def get_invoices(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
    q: Annotated[str | None, Query(min_length=2)] = None,
    status: str | None = None,
) -> list[SalesDocumentRead]:
    """Lista facturas y notas de credito del tenant activo.

    Cambio aditivo al contrato (Fase 5): ``q`` filtra por coincidencia parcial
    de secuencial o clave de acceso, ``status`` por estado exacto. Siempre
    tenant-scoped y acotado a 100 resultados (``billing.list_sales_documents``),
    igual que el resto de listados del backend.
    """

    entities = await billing.list_sales_documents(session, context, query=q, status=status)
    return [await billing.to_sales_document_read(session, context, entity) for entity in entities]


@router.get("/invoices/{invoice_id}", response_model=SalesDocumentRead)
async def get_invoice(
    invoice_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
) -> SalesDocumentRead:
    entity = await billing.get_sales_document(session, context, invoice_id)
    return await billing.to_sales_document_read(session, context, entity)


@router.get("/invoices/{invoice_id}/artifacts", response_model=list[DocumentArtifactRead])
async def get_invoice_artifacts(
    invoice_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
) -> list[DocumentArtifactRead]:
    return await billing.list_document_artifacts(session, context, invoice_id)


@router.get(
    "/invoices/{invoice_id}/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadRead,
)
async def get_invoice_artifact_download(
    invoice_id: uuid.UUID,
    artifact_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
) -> ArtifactDownloadRead:
    return await billing.create_artifact_download(session, context, invoice_id, artifact_id)


@router.post("/invoices/{invoice_id}/issue", response_model=OperationRead, status_code=202)
async def post_invoice_issue(
    invoice_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    """Emite una factura: firma sincrona + transmision SRI asincrona (202).

    La firma XAdES-BES, el XML, el RIDE y la subida a MinIO ocurren de forma
    sincrona dentro de esta llamada (``billing.issue_document``); el
    ``OperationRecord`` devuelto queda en ``PROCESSING`` porque la
    transmision/autorizacion SRI las completa
    ``workers/sri_transmission.py`` de forma asincrona a partir del evento
    outbox ``invoice.signed`` (ver decision 8 de ``docs/sprints/sprint-02.md``).
    Repetir la misma ``Idempotency-Key`` devuelve el mismo ``Operation`` sin
    crear una segunda transmision ni un segundo evento outbox.
    """

    async def issue() -> tuple[str, dict[str, object]]:
        correlation_id = str(uuid.uuid4())
        document = await billing.issue_document(
            session,
            context,
            invoice_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        operation = OperationRecord(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            operation_type="invoices.issue",
            status="PROCESSING",
            correlation_id=correlation_id,
            result={"sales_document_id": str(document.id), "status": document.status},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(operation)
        await session.flush()
        response = OperationRead(
            operation_id=operation.id,
            status=operation.status,
            correlation_id=operation.correlation_id,
            created_at=operation.created_at,
            expires_at=operation.expires_at,
            result=operation.result,
            error=operation.error,
        ).model_dump(mode="json", by_alias=True)
        return str(document.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.issue",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id)},
        action="invoice.issued",
        entity_type="sales_document",
        callback=issue,
        event_type="invoice.signed",
    )


@router.post("/credit-notes", response_model=OperationRead, status_code=202)
async def post_credit_note(
    data: CreditNoteInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("credit-notes:issue"))],
) -> dict[str, object]:
    """Crea y emite una nota de credito relacionada a una factura AUTHORIZED (202).

    Un unico endpoint cubre creacion + emision (``createAndIssueCreditNote``
    en ``contracts/openapi.yaml``): valida la factura de sustento y el saldo
    acreditable (``billing.create_credit_note``), y reutiliza el mismo
    pipeline sincrono de firma/XML/RIDE/MinIO que una factura
    (``billing.issue_document``) antes de encolar la transmision SRI via el
    evento outbox ``invoice.signed``. Se audita ``credit_note.created`` (la
    creacion y validacion del saldo acreditable) ademas de
    ``credit_note.issued`` (que ``execute_idempotent`` agrega automaticamente
    a partir de ``action``). Repetir la misma ``Idempotency-Key`` devuelve el
    mismo ``Operation`` sin crear una segunda nota de credito, transmision ni
    evento outbox.
    """

    async def create_and_issue() -> tuple[str, dict[str, object]]:
        correlation_id = str(uuid.uuid4())
        draft = await billing.create_credit_note(session, context, data)
        await append_audit(
            session,
            context=context,
            action="credit_note.created",
            entity_type="sales_document",
            entity_id=str(draft.id),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            details={"related_invoice_id": str(data.invoice_id), "total": str(draft.total)},
        )
        document = await billing.issue_document(
            session,
            context,
            draft.id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        operation = OperationRecord(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            operation_type="credit_notes.create_and_issue",
            status="PROCESSING",
            correlation_id=correlation_id,
            result={"sales_document_id": str(document.id), "status": document.status},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(operation)
        await session.flush()
        response = OperationRead(
            operation_id=operation.id,
            status=operation.status,
            correlation_id=operation.correlation_id,
            created_at=operation.created_at,
            expires_at=operation.expires_at,
            result=operation.result,
            error=operation.error,
        ).model_dump(mode="json", by_alias=True)
        return str(document.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="credit_notes.create_and_issue",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="credit_note.issued",
        entity_type="sales_document",
        callback=create_and_issue,
        event_type="invoice.signed",
    )


def _account_item_response(item: AccountItemRead) -> dict[str, object]:
    return item.model_dump(mode="json", by_alias=True)


def _summary_to_account_item(summary: receivables.ReceivableSummary) -> AccountItemRead:
    return AccountItemRead(
        id=summary.id,
        party_id=summary.party_id,
        status=summary.status,
        original_amount=summary.original_amount,
        open_amount=summary.open_amount,
        currency=summary.currency,
        due_date=summary.due_date,
        aging=(
            {"bucket": summary.aging_bucket, "days_overdue": summary.aging_days_overdue}
            if summary.aging_bucket is not None
            else None
        ),
    )


@router.get("/receivables", response_model=list[AccountItemRead])
async def get_receivables(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
    status: str | None = None,
    due_before: Annotated[date | None, Query(alias="dueBefore")] = None,
) -> list[dict[str, object]]:
    """Consulta la cartera del tenant activo (Sprint 3, Fase 1: solo lectura).

    ``status``/``dueBefore`` siguen el contrato ya publicado
    (``contracts/openapi.yaml``); el ``Receivable`` solo existe si fue creado
    por ``workers/receivables.py::handle_invoice_authorized`` -- no hay
    endpoint de creacion manual. ``dueBefore`` presente activa el calculo de
    aging (misma fecha se usa como ``as_of``), igual que en ``receivables.list``
    (MCP).
    """

    as_of = due_before if due_before is not None else None
    items = await receivables.list_receivables(
        session, tenant_id=context.tenant_id, status=status, as_of=as_of
    )
    return [_account_item_response(item) for item in items]


@router.get("/receivables/aging", response_model=AgingSummaryRead)
async def get_receivables_aging(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
    as_of: Annotated[date | None, Query(alias="asOf")] = None,
) -> dict[str, object]:
    """Resumen de aging por tenant (Sprint 3 Fase 3: E5-05).

    Declarado ANTES de ``GET /receivables/{receivable_id}`` para que FastAPI
    no interprete ``aging`` como un ``receivable_id`` invalido: las rutas
    estaticas deben registrarse antes que las dinamicas con el mismo prefijo.
    ``asOf`` permite fijar la fecha de corte local (``America/Guayaquil``)
    para pruebas reproducibles; por defecto es hoy. La logica de
    clasificacion vive integramente en
    ``services/receivables.py::compute_aging_summary`` (funcion pura sobre
    ``classify_aging_bucket``), nunca duplicada aqui.
    """

    summary = await receivables.compute_aging_summary(session, context=context, as_of=as_of)
    return AgingSummaryRead(
        as_of=summary.as_of,
        buckets=[
            AgingBucketTotalRead(
                bucket=bucket.bucket,
                total=bucket.total,
                installment_count=bucket.installment_count,
            )
            for bucket in summary.buckets
        ],
        by_party=[
            PartyAgingBucketTotalRead(
                party_id=party_bucket.party_id,
                bucket=party_bucket.bucket,
                total=party_bucket.total,
                installment_count=party_bucket.installment_count,
            )
            for party_bucket in summary.by_party
        ],
    ).model_dump(mode="json", by_alias=True)


@router.get("/receivables/collection-policy", response_model=CollectionPolicyRead)
async def get_collection_policy(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
) -> CollectionPolicyRead:
    policy = await session.get(CollectionPolicy, context.tenant_id)
    if policy is None:
        policy = CollectionPolicy(tenant_id=context.tenant_id)
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
    return CollectionPolicyRead(
        enabled=policy.enabled,
        offsets_days=[int(item) for item in policy.offsets_days.split(",") if item],
        channels=[item for item in policy.channels.split(",") if item],
        send_hour=policy.send_hour,
        email_template_id=policy.email_template_id,
        whatsapp_template_id=policy.whatsapp_template_id,
        updated_at=policy.updated_at,
    )


@router.put("/receivables/collection-policy", response_model=CollectionPolicyRead)
async def put_collection_policy(
    data: CollectionPolicyUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:notify"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        policy = await session.get(CollectionPolicy, context.tenant_id)
        if policy is None:
            policy = CollectionPolicy(tenant_id=context.tenant_id)
            session.add(policy)
        policy.enabled = data.enabled
        policy.offsets_days = ",".join(str(item) for item in sorted(set(data.offsets_days)))
        policy.channels = ",".join(dict.fromkeys(data.channels))
        policy.send_hour = data.send_hour
        policy.email_template_id = data.email_template_id
        policy.whatsapp_template_id = data.whatsapp_template_id
        await session.flush()
        response = CollectionPolicyRead(
            **data.model_dump(), updated_at=policy.updated_at
        ).model_dump(mode="json", by_alias=True)
        return str(context.tenant_id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.collection_policy.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="collection_policy.updated",
        entity_type="collection_policy",
        callback=update,
    )


@router.get("/receivables/{receivable_id}", response_model=AccountItemRead)
async def get_receivable(
    receivable_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
    as_of: Annotated[date | None, Query(alias="asOf")] = None,
) -> dict[str, object]:
    """Consulta el detalle de un receivable, incluyendo su bucket de aging.

    ``asOf`` (Sprint 3 Fase 3, aditivo) fija la fecha de corte local usada
    para derivar ``AccountItem.aging``/``status`` (``OVERDUE``); por defecto
    hoy en ``America/Guayaquil``. Permite reproducibilidad en pruebas sin
    depender del reloj real, igual que ``GET /receivables/aging``.
    """

    entity = await receivables.get_receivable(
        session, tenant_id=context.tenant_id, receivable_id=receivable_id
    )
    summary = await receivables.to_receivable_summary(
        session, tenant_id=context.tenant_id, receivable=entity, as_of=as_of
    )
    return _account_item_response(_summary_to_account_item(summary))


@router.get("/receivables/{receivable_id}/movements", response_model=list[MovementRead])
async def get_receivable_movements(
    receivable_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
) -> list[dict[str, object]]:
    """Historial de movimientos de un receivable (cobros, retenciones,
    descuentos, NC, reversos).

    Necesario para que la UI muestre el drawer de historial
    (``docs/sprints/sprint-03.md`` decision 10); no declarado en Sprint 0
    porque ``Movement`` no existia todavia. Aditivo sobre el contrato ya
    publicado.
    """

    movements = await receivables.list_movements(
        session, tenant_id=context.tenant_id, receivable_id=receivable_id
    )
    return [
        MovementRead(
            id=movement.id,
            receivable_id=movement.receivable_id,
            installment_id=movement.installment_id,
            movement_type=movement.movement_type,
            amount=movement.amount,
            support_reference=movement.support_reference,
            reversed_movement_id=movement.reversed_movement_id,
            actor_id=movement.actor_id,
            created_at=movement.created_at,
        ).model_dump(mode="json", by_alias=True)
        for movement in movements
    ]


@router.post(
    "/receivables/{receivable_id}/payments",
    response_model=AccountItemRead,
    status_code=201,
)
async def post_receivable_payment(
    receivable_id: uuid.UUID,
    data: PaymentInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
) -> dict[str, object]:
    """Registra un cobro parcial o total con retenciones y descuentos (E5-03/E5-04).

    Idempotente por ``Idempotency-Key`` (``execute_idempotent``): repetir la
    misma clave devuelve el mismo ``AccountItem`` sin crear un segundo
    ``Movement``. La logica de asignacion a cuotas, validacion de saldo y
    actualizacion de estado vive integramente en
    ``services/receivables.py::record_payment`` (bajo ``lock_receivable``,
    ``SELECT ... FOR UPDATE``), nunca duplicada aqui.
    """

    async def apply_payment() -> tuple[str, dict[str, object]]:
        correlation_id = str(uuid.uuid4())
        summary = await receivables.record_payment(
            session,
            context,
            receivable_id,
            data,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return str(receivable_id), _account_item_response(_summary_to_account_item(summary))

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.record_payment",
        idempotency_key=idempotency_key,
        request_payload={"receivable_id": str(receivable_id), **data.model_dump(mode="json")},
        action="receivable.payment_registered",
        entity_type="receivable",
        callback=apply_payment,
    )


@router.post(
    "/receivables/{receivable_id}/reminders",
    response_model=ReminderRead,
    status_code=201,
)
async def post_receivable_reminder(
    receivable_id: uuid.UUID,
    data: ReminderInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:notify"))],
) -> dict[str, object]:
    async def send() -> tuple[str, dict[str, object]]:
        entity = await receivables.send_real_reminder(
            session,
            context,
            receivable_id=receivable_id,
            reminder=data,
        )
        response = ReminderRead.model_validate(entity).model_dump(mode="json", by_alias=True)
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.reminder.send",
        idempotency_key=idempotency_key,
        request_payload={"receivable_id": str(receivable_id), **data.model_dump(mode="json")},
        action="receivable.reminder_requested",
        entity_type="collection_reminder",
        callback=send,
    )


@router.post(
    "/receivables/{receivable_id}/movements/{movement_id}/reversal",
    response_model=AccountItemRead,
    status_code=201,
)
async def post_movement_reversal(
    receivable_id: uuid.UUID,
    movement_id: uuid.UUID,
    data: ReversalInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
) -> dict[str, object]:
    """Revierte un movimiento como compensacion auditada (E5-09).

    Aditivo sobre el contrato publicado (decision 7 del sprint). Idempotente
    por ``Idempotency-Key`` (``execute_idempotent``): repetir la misma clave
    devuelve el mismo ``AccountItem`` sin crear un segundo ``REVERSAL``. La
    logica (validar que el original no sea ya un ``REVERSAL``, que no haya
    sido revertido antes, el efecto sobre ``CustomerCredit`` si aplica, y el
    recalculo de saldo) vive integramente en
    ``services/receivables.py::reverse_movement``, bajo ``lock_receivable``,
    nunca duplicada aqui. No expuesto como tool MCP en este sprint (decision
    9: revertir es sensible, se mantiene solo en REST/UI humana).
    """

    async def apply_reversal() -> tuple[str, dict[str, object]]:
        correlation_id = str(uuid.uuid4())
        summary = await receivables.reverse_movement(
            session,
            context,
            receivable_id=receivable_id,
            movement_id=movement_id,
            reason=data.reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return str(receivable_id), _account_item_response(_summary_to_account_item(summary))

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.reverse_movement",
        idempotency_key=idempotency_key,
        request_payload={
            "receivable_id": str(receivable_id),
            "movement_id": str(movement_id),
            **data.model_dump(mode="json"),
        },
        # La auditoria de dominio ``movement.reversed`` (con original_movement_id)
        # la escribe el servicio; execute_idempotent audita la operacion con una
        # accion distinta para no duplicar el mismo evento en el hash-chain.
        action="receivable.reversal_operation",
        entity_type="receivable",
        callback=apply_reversal,
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

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, create_dev_token, require_scopes
from app.core.config import get_settings
from app.db.session import get_session
from app.models.billing import SalesDocument
from app.models.legal_commercial import ContractVersion
from app.models.platform import (
    AutomationSettings,
    Membership,
    OperationRecord,
    Tenant,
    User,
)
from app.models.receivables import CollectionPolicy
from app.schemas.bank_reconciliation import BankStatementImportRead
from app.schemas.billing import (
    ArtifactDownloadRead,
    CreditNoteInput,
    DocumentArtifactRead,
    InvoiceCollectionUpdate,
    InvoiceEmailInput,
    InvoiceEmailPreviewRead,
    InvoiceEmailRead,
    InvoiceInput,
    InvoicePreviewInput,
    InvoicePreviewRead,
    SalesDocumentArchiveInput,
    SalesDocumentRead,
)
from app.schemas.legal_commercial import (
    AwsConsumptionCutCreate,
    AwsConsumptionCutRead,
    BillingProposalCreate,
    BillingProposalRead,
    CommercialContractCreate,
    CommercialContractRead,
    ContractArtifactDownloadRead,
    ContractBillingPrepare,
    ContractEmailSend,
    ContractEmailSyncRead,
    ContractVersionCreate,
    ContractVersionRead,
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
    TaxCategoryCreate,
    TaxCategoryRead,
)
from app.schemas.platform import (
    AutomationSettingsRead,
    AutomationSettingsUpdate,
    DevTokenRequest,
    FiscalSettingsRead,
    FiscalSettingsUpdate,
    InvoiceEmailTemplateRead,
    InvoiceEmailTemplateUpdate,
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
    CollectionsBreakdownRead,
    CollectionsHistoryRead,
    MovementRead,
    PartyAgingBucketTotalRead,
    PaymentInput,
    ReceivableDueDateUpdate,
    ReminderInput,
    ReminderRead,
    RetentionBatchRead,
    RetentionXmlPreviewRead,
    ReversalInput,
)
from app.services import (
    bank_reconciliation,
    billing,
    fiscal_settings,
    legal_commercial,
    masters,
    receivables,
)
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
    "commercial:read",
    "commercial:write",
    "tax:read",
    "tax:write",
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


@router.get(
    "/organization/invoice-email-template",
    response_model=InvoiceEmailTemplateRead,
)
async def get_invoice_email_template(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:read"))],
) -> InvoiceEmailTemplateRead:
    return await fiscal_settings.read_invoice_email_template(session, context)


@router.put(
    "/organization/invoice-email-template",
    response_model=InvoiceEmailTemplateRead,
)
async def put_invoice_email_template(
    data: InvoiceEmailTemplateUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        response = await fiscal_settings.update_invoice_email_template(session, context, data)
        return str(context.tenant_id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="organization.invoice_email_template.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="organization.invoice_email_template.updated",
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


@router.post("/organization/ride-logo", response_model=FiscalSettingsRead)
async def post_ride_logo(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    logo_bytes = await file.read(fiscal_settings.MAX_RIDE_LOGO_SIZE + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        response = await fiscal_settings.upload_ride_logo(
            session,
            context,
            filename=file.filename,
            data=logo_bytes,
        )
        return str(context.tenant_id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="organization.ride_logo.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "filename": file.filename,
            "sha256": hashlib.sha256(logo_bytes).hexdigest(),
        },
        action="organization.ride_logo.uploaded",
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


@router.post("/tax-categories", response_model=TaxCategoryRead, status_code=201)
async def post_tax_category(
    data: TaxCategoryCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("organization:write"))],
) -> dict[str, object]:
    """Da de alta una categoría tributaria con fecha de vigencia."""

    async def create() -> tuple[str, dict[str, object]]:
        entity = await masters.create_tax_category(session, context, data)
        return (
            str(entity.id),
            TaxCategoryRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="tax_categories.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="tax_category.created",
        entity_type="tax_category",
        callback=create,
    )


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


@router.post("/commercial/contracts", response_model=CommercialContractRead, status_code=201)
async def post_commercial_contract(
    data: CommercialContractCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.create_contract(session, context, data)
        return str(entity.id), CommercialContractRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contracts.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="commercial_contract.created",
        entity_type="commercial_contract",
        callback=create,
    )


@router.get("/commercial/contracts", response_model=list[CommercialContractRead])
async def get_commercial_contracts(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
    party_id: uuid.UUID | None = None,
) -> list[CommercialContractRead]:
    return [
        CommercialContractRead.model_validate(entity)
        for entity in await legal_commercial.list_contracts(session, context, party_id)
    ]


@router.post(
    "/commercial/contracts/{contract_id}/versions",
    response_model=ContractVersionRead,
    status_code=201,
)
async def post_contract_version(
    contract_id: uuid.UUID,
    data: ContractVersionCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.create_contract_version(session, context, contract_id, data)
        return str(entity.id), ContractVersionRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contract_versions.create",
        idempotency_key=idempotency_key,
        request_payload={"contract_id": str(contract_id), **data.model_dump(mode="json")},
        action="commercial_contract_version.created",
        entity_type="commercial_contract_version",
        callback=create,
    )


@router.get(
    "/commercial/contracts/{contract_id}/versions", response_model=list[ContractVersionRead]
)
async def get_contract_versions(
    contract_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
) -> list[ContractVersionRead]:
    return [
        ContractVersionRead.model_validate(entity)
        for entity in await legal_commercial.list_contract_versions(session, context, contract_id)
    ]


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/sent-pdf",
    response_model=ContractVersionRead,
)
async def post_sent_contract_pdf(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    data = await file.read(legal_commercial.MAX_SIGNED_CONTRACT_BYTES + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.upload_sent_contract(
            session,
            context,
            contract_id=contract_id,
            version_id=version_id,
            filename=file.filename,
            data=data,
        )
        return str(entity.id), ContractVersionRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contract_versions.sent_pdf.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "contract_id": str(contract_id),
            "version_id": str(version_id),
            "filename": file.filename,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="commercial_contract_version.sent_pdf_uploaded",
        entity_type="commercial_contract_version",
        callback=upload,
    )


@router.get(
    "/commercial/contracts/{contract_id}/versions/{version_id}/sent-pdf",
    response_model=ContractArtifactDownloadRead,
)
async def get_sent_contract_pdf(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
    inline: bool = Query(default=False),
) -> ContractArtifactDownloadRead:
    download_url, file_name = await legal_commercial.sent_contract_download(
        session, context, contract_id=contract_id, version_id=version_id, inline=inline
    )
    return ContractArtifactDownloadRead(
        download_url=download_url, expires_in_seconds=300, file_name=file_name
    )


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/email",
    response_model=ContractVersionRead,
)
async def post_contract_email(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ContractEmailSend,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[
        AuthContext, Depends(require_scopes("commercial:write", "communications:write"))
    ],
) -> dict[str, object]:
    async def send() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.send_contract_email(
            session, context, contract_id=contract_id, version_id=version_id, data=data
        )
        return str(entity.id), ContractVersionRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contract_versions.email",
        idempotency_key=idempotency_key,
        request_payload={
            "contract_id": str(contract_id),
            "version_id": str(version_id),
            **data.model_dump(mode="json"),
        },
        action="commercial_contract_version.emailed",
        entity_type="commercial_contract_version",
        callback=send,
    )


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/email-sync",
    response_model=ContractEmailSyncRead,
)
async def post_contract_email_sync(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[
        AuthContext, Depends(require_scopes("commercial:write", "communications:read"))
    ],
) -> dict[str, object]:
    async def sync() -> tuple[str, dict[str, object]]:
        result = await legal_commercial.sync_contract_email(
            session, context, contract_id=contract_id, version_id=version_id
        )
        return str(version_id), result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contract_versions.email_sync",
        idempotency_key=idempotency_key,
        request_payload={"contract_id": str(contract_id), "version_id": str(version_id)},
        action="commercial_contract_version.email_synced",
        entity_type="commercial_contract_version",
        callback=sync,
    )


async def _contract_version_action(
    *,
    session: AsyncSession,
    context: AuthContext,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: str,
    operation: str,
    action: str,
    callback: Callable[..., Awaitable[ContractVersion]],
) -> dict[str, object]:
    async def run() -> tuple[str, dict[str, object]]:
        entity = await callback(session, context, contract_id=contract_id, version_id=version_id)
        return str(entity.id), ContractVersionRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation=operation,
        idempotency_key=idempotency_key,
        request_payload={"contract_id": str(contract_id), "version_id": str(version_id)},
        action=action,
        entity_type="commercial_contract_version",
        callback=run,
    )


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/confirm-firmaec",
    response_model=ContractVersionRead,
)
async def post_contract_firmaec_confirmation(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    return await _contract_version_action(
        session=session,
        context=context,
        contract_id=contract_id,
        version_id=version_id,
        idempotency_key=idempotency_key,
        operation="commercial.contract_versions.confirm_firmaec",
        action="commercial_contract_version.firmaec_confirmed",
        callback=legal_commercial.confirm_firmaec,
    )


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/activate",
    response_model=ContractVersionRead,
)
async def post_contract_activation(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    return await _contract_version_action(
        session=session,
        context=context,
        contract_id=contract_id,
        version_id=version_id,
        idempotency_key=idempotency_key,
        operation="commercial.contract_versions.activate",
        action="commercial_contract_version.activated",
        callback=legal_commercial.activate_contract,
    )


@router.post(
    "/commercial/contracts/{contract_id}/versions/{version_id}/signed-pdf",
    response_model=ContractVersionRead,
)
async def post_signed_contract_pdf(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    data = await file.read(legal_commercial.MAX_SIGNED_CONTRACT_BYTES + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.upload_signed_contract(
            session,
            context,
            contract_id=contract_id,
            version_id=version_id,
            filename=file.filename,
            data=data,
        )
        return (
            str(entity.id),
            ContractVersionRead.model_validate(entity).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contract_versions.signed_pdf.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "contract_id": str(contract_id),
            "version_id": str(version_id),
            "filename": file.filename,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="commercial_contract_version.signed_pdf_uploaded",
        entity_type="commercial_contract_version",
        callback=upload,
    )


@router.get(
    "/commercial/contracts/{contract_id}/versions/{version_id}/signed-pdf",
    response_model=ContractArtifactDownloadRead,
)
async def get_signed_contract_pdf(
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
    inline: bool = Query(default=False),
) -> ContractArtifactDownloadRead:
    download_url, file_name = await legal_commercial.signed_contract_download(
        session, context, contract_id=contract_id, version_id=version_id, inline=inline
    )
    return ContractArtifactDownloadRead(
        download_url=download_url, expires_in_seconds=300, file_name=file_name
    )


@router.post(
    "/commercial/aws-consumption-cuts", response_model=AwsConsumptionCutRead, status_code=201
)
async def post_aws_consumption_cut(
    data: AwsConsumptionCutCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.create_aws_cut(session, context, data)
        return str(entity.id), AwsConsumptionCutRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.aws_cuts.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="aws_consumption_cut.created",
        entity_type="aws_consumption_cut",
        callback=create,
    )


@router.get("/commercial/aws-consumption-cuts", response_model=list[AwsConsumptionCutRead])
async def get_aws_consumption_cuts(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
    party_id: uuid.UUID | None = None,
) -> list[AwsConsumptionCutRead]:
    return [
        AwsConsumptionCutRead.model_validate(entity)
        for entity in await legal_commercial.list_aws_cuts(session, context, party_id=party_id)
    ]


@router.post(
    "/commercial/aws-consumption-cuts/{cut_id}/evidence",
    response_model=AwsConsumptionCutRead,
)
async def post_aws_consumption_evidence(
    cut_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    data = await file.read(legal_commercial.MAX_REPORT_BYTES + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.upload_aws_evidence(
            session, context, cut_id=cut_id, filename=file.filename, data=data
        )
        return str(entity.id), AwsConsumptionCutRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.aws_cuts.evidence.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "cut_id": str(cut_id),
            "filename": file.filename,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="aws_consumption_cut.evidence_uploaded",
        entity_type="aws_consumption_cut",
        callback=upload,
    )


@router.post(
    "/commercial/aws-consumption-cuts/{cut_id}/confirm",
    response_model=AwsConsumptionCutRead,
)
async def post_aws_consumption_confirmation(
    cut_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def confirm() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.confirm_aws_cut(session, context, cut_id)
        return str(entity.id), AwsConsumptionCutRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.aws_cuts.confirm",
        idempotency_key=idempotency_key,
        request_payload={"cut_id": str(cut_id)},
        action="aws_consumption_cut.reviewed",
        entity_type="aws_consumption_cut",
        callback=confirm,
    )


@router.post("/commercial/billing-proposals", response_model=BillingProposalRead, status_code=201)
async def post_billing_proposal(
    data: BillingProposalCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.create_billing_proposal(session, context, data)
        return str(entity.id), BillingProposalRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.billing_proposals.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="commercial_billing_proposal.created",
        entity_type="commercial_billing_proposal",
        callback=create,
    )


@router.get("/commercial/billing-proposals", response_model=list[BillingProposalRead])
async def get_billing_proposals(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:read"))],
    contract_id: uuid.UUID | None = None,
) -> list[BillingProposalRead]:
    return [
        BillingProposalRead.model_validate(entity)
        for entity in await legal_commercial.list_billing_proposals(
            session, context, contract_id=contract_id
        )
    ]


@router.post(
    "/commercial/contracts/{contract_id}/prepare-billing",
    response_model=BillingProposalRead,
    status_code=201,
)
async def post_prepare_contract_billing(
    contract_id: uuid.UUID,
    data: ContractBillingPrepare,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def prepare() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.prepare_contract_billing(
            session, context, contract_id=contract_id, data=data
        )
        return str(entity.id), BillingProposalRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.contracts.prepare_billing",
        idempotency_key=idempotency_key,
        request_payload={"contract_id": str(contract_id), **data.model_dump(mode="json")},
        action="commercial_billing_proposal.prepared",
        entity_type="commercial_billing_proposal",
        callback=prepare,
    )


@router.post(
    "/commercial/billing-proposals/{proposal_id}/report",
    response_model=BillingProposalRead,
)
async def post_billing_proposal_report(
    proposal_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    data = await file.read(legal_commercial.MAX_REPORT_BYTES + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.upload_billing_report(
            session, context, proposal_id=proposal_id, filename=file.filename, data=data
        )
        return str(entity.id), BillingProposalRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.billing_proposals.report.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "proposal_id": str(proposal_id),
            "filename": file.filename,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        action="commercial_billing_proposal.report_uploaded",
        entity_type="commercial_billing_proposal",
        callback=upload,
    )


@router.post(
    "/commercial/billing-proposals/{proposal_id}/report/approve",
    response_model=BillingProposalRead,
)
async def post_billing_proposal_report_approval(
    proposal_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write"))],
) -> dict[str, object]:
    async def approve() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.approve_billing_report(session, context, proposal_id)
        return str(entity.id), BillingProposalRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.billing_proposals.report.approve",
        idempotency_key=idempotency_key,
        request_payload={"proposal_id": str(proposal_id)},
        action="commercial_billing_proposal.report_approved",
        entity_type="commercial_billing_proposal",
        callback=approve,
    )


@router.post(
    "/commercial/billing-proposals/{proposal_id}/create-invoice-draft",
    response_model=SalesDocumentRead,
    status_code=201,
)
async def post_billing_proposal_conversion(
    proposal_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("commercial:write", "invoices:write"))],
) -> dict[str, object]:
    async def convert() -> tuple[str, dict[str, object]]:
        _, document = await legal_commercial.convert_billing_proposal(session, context, proposal_id)
        response = await billing.to_sales_document_read(session, context, document)
        return str(document.id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="commercial.billing_proposals.create_invoice_draft",
        idempotency_key=idempotency_key,
        request_payload={"proposal_id": str(proposal_id)},
        action="invoice.draft_created_from_commercial_proposal",
        entity_type="sales_document",
        callback=convert,
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


@router.post("/invoices/{invoice_id}/duplicate", response_model=SalesDocumentRead, status_code=201)
async def post_invoice_duplicate(
    invoice_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    """Crea un nuevo borrador a partir de una factura existente del tenant."""

    async def duplicate() -> tuple[str, dict[str, object]]:
        entity = await billing.duplicate_invoice_draft(session, context, invoice_id)
        response_model = await billing.to_sales_document_read(session, context, entity)
        return str(entity.id), response_model.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.duplicate",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id)},
        action="invoice.duplicated",
        entity_type="sales_document",
        callback=duplicate,
    )


@router.put("/invoices/{invoice_id}/collection-policy", response_model=SalesDocumentRead)
async def put_invoice_collection_policy(
    invoice_id: uuid.UUID,
    data: InvoiceCollectionUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await billing.update_invoice_collection_policy(
            session, context, invoice_id, enabled=data.enabled
        )
        response = await billing.to_sales_document_read(session, context, entity)
        return str(entity.id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.collection_policy.update",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id), **data.model_dump(mode="json")},
        action="invoice.collection_policy_updated",
        entity_type="sales_document",
        callback=update,
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


@router.post("/invoices/{invoice_id}/archive", response_model=SalesDocumentRead)
async def post_invoice_archive(
    invoice_id: uuid.UUID,
    data: SalesDocumentArchiveInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    """Archiva un rechazo SRI sin eliminar evidencia ni auditoria fiscal."""

    async def archive() -> tuple[str, dict[str, object]]:
        entity = await billing.archive_failed_sales_document(
            session, context, invoice_id, reason=data.reason
        )
        response_model = await billing.to_sales_document_read(session, context, entity)
        return str(entity.id), response_model.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.archive_failed",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id), "reason": data.reason},
        action="invoice.archived",
        entity_type="sales_document",
        callback=archive,
    )


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
    inline: bool = Query(default=False),
) -> ArtifactDownloadRead:
    return await billing.create_artifact_download(
        session, context, invoice_id, artifact_id, inline=inline
    )


@router.post("/invoices/{invoice_id}/email", response_model=InvoiceEmailRead)
async def post_invoice_email(
    invoice_id: uuid.UUID,
    data: InvoiceEmailInput,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:write"))],
) -> dict[str, object]:
    """Envía, tras confirmación humana, el RIDE y XML de una factura autorizada."""

    async def send() -> tuple[str, dict[str, object]]:
        result = await billing.send_invoice_email(
            session, context, invoice_id, recipient=str(data.recipient)
        )
        return result.message_id, result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.email",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id), "recipient": str(data.recipient)},
        action="invoice.emailed",
        entity_type="sales_document",
        callback=send,
    )


@router.get(
    "/invoices/{invoice_id}/email-preview",
    response_model=InvoiceEmailPreviewRead,
)
async def get_invoice_email_preview(
    invoice_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("invoices:read"))],
) -> InvoiceEmailPreviewRead:
    return await billing.preview_invoice_email(session, context, invoice_id)


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
        invoice_sequential=summary.invoice_sequential,
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


@router.get("/receivables/collections", response_model=CollectionsBreakdownRead)
async def get_receivables_collections(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> dict[str, object]:
    """Desglose del cobro: cuánto entró en dinero y cuánto quedó retenido.

    Ruta estatica declarada ANTES de ``GET /receivables/{receivable_id}``, por
    la misma razon que ``/receivables/aging``. El calculo vive integramente en
    ``services/receivables.py::compute_collections_breakdown``, que reusa la
    regla de movimientos activos de ``compute_installment_balance`` para que el
    desglose jamas contradiga el saldo de la cartera.
    """

    breakdown = await receivables.compute_collections_breakdown(
        session, context=context, from_date=from_date, to_date=to_date
    )
    return breakdown.model_dump(mode="json", by_alias=True)


@router.get("/receivables/collections/monthly", response_model=CollectionsHistoryRead)
async def get_receivables_collections_monthly(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:read"))],
    months: Annotated[int, Query(ge=1, le=36)] = 12,
    as_of: Annotated[date | None, Query(alias="asOf")] = None,
) -> dict[str, object]:
    """Serie mensual de cobro, para leer la tendencia y no solo el total.

    Ruta estatica declarada ANTES de ``GET /receivables/{receivable_id}``.
    ``asOf`` fija el mes final de la ventana para pruebas reproducibles; por
    defecto es hoy en ``America/Guayaquil``.
    """

    history = await receivables.compute_collections_history(
        session, context=context, months=months, as_of=as_of
    )
    return history.model_dump(mode="json", by_alias=True)


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
        email_subject=policy.email_subject,
        email_body=policy.email_body,
        payment_instructions=policy.payment_instructions,
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
        policy.email_subject = data.email_subject
        policy.email_body = data.email_body
        policy.payment_instructions = data.payment_instructions
        await session.flush()
        # ``updated_at`` is generated by PostgreSQL.  After a flush SQLAlchemy
        # expires that server-managed attribute; refresh it explicitly before
        # building the async response to avoid an implicit synchronous load.
        await session.refresh(policy)
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
            effective_date=movement.effective_date,
            support_reference=movement.support_reference,
            reversed_movement_id=movement.reversed_movement_id,
            actor_id=movement.actor_id,
            created_at=movement.created_at,
        ).model_dump(mode="json", by_alias=True)
        for movement in movements
    ]


@router.put("/receivables/{receivable_id}/due-date", response_model=AccountItemRead)
async def put_receivable_due_date(
    receivable_id: uuid.UUID,
    data: ReceivableDueDateUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
) -> dict[str, object]:
    """Corrige vencimiento comercial y cartera sin alterar el comprobante SRI."""

    async def update() -> tuple[str, dict[str, object]]:
        summary = await receivables.correct_receivable_due_date(
            session,
            context,
            receivable_id=receivable_id,
            due_date=data.due_date,
            reason=data.reason,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
        )
        return str(receivable_id), _account_item_response(_summary_to_account_item(summary))

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.due_date.correct",
        idempotency_key=idempotency_key,
        request_payload={"receivable_id": str(receivable_id), **data.model_dump(mode="json")},
        action="receivable.due_date_corrected",
        entity_type="receivable",
        callback=update,
    )


@router.post(
    "/receivables/retention-batch",
    response_model=RetentionBatchRead,
)
async def post_retention_batch(
    files: Annotated[list[UploadFile], File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
    apply: Annotated[bool, Form()] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    """Relaciona varios XML autorizados y registra solo las coincidencias exactas."""
    if not files:
        raise HTTPException(status_code=422, detail="At least one XML file is required")
    if len(files) > 50:
        raise HTTPException(status_code=422, detail="A maximum of 50 XML files is allowed")
    parsed_files = [
        (file.filename or "retencion.xml", await file.read(receivables.MAX_RETENTION_XML_BYTES + 1))
        for file in files
    ]
    if not apply:
        result = await receivables.import_retention_xml_batch(
            session,
            context=context,
            files=parsed_files,
            apply=False,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"preview-{uuid.uuid4()}",
        )
        return result.model_dump(mode="json", by_alias=True)

    if idempotency_key is None or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(
            status_code=422,
            detail=(
                "An Idempotency-Key between 16 and 128 characters is required "
                "to register retentions"
            ),
        )

    async def register_batch() -> tuple[str, dict[str, object]]:
        result = await receivables.import_retention_xml_batch(
            session,
            context=context,
            files=parsed_files,
            apply=True,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
        )
        return str(context.tenant_id), result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.retention_batch.register",
        idempotency_key=idempotency_key,
        request_payload={
            "files": [
                {"name": name, "sha256": hashlib.sha256(content).hexdigest()}
                for name, content in parsed_files
            ],
        },
        action="receivable.retention_batch_registered",
        entity_type="receivable_batch",
        callback=register_batch,
    )


@router.post(
    "/receivables/bank-statement",
    response_model=BankStatementImportRead,
)
async def post_bank_statement(
    file: Annotated[UploadFile, File()],
    period: Annotated[str, Form(pattern=r"^\d{4}-\d{2}$")],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
    apply: Annotated[bool, Form()] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    """Cruza abonos del periodo y registra solo cobros totales con match único."""
    try:
        period_date = datetime.strptime(period, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Period must use YYYY-MM") from exc
    content = await file.read(bank_reconciliation.MAX_BANK_STATEMENT_BYTES + 1)
    file_name = file.filename or "estado-bancario.txt"
    if not apply:
        result = await bank_reconciliation.import_bank_statement(
            session,
            context=context,
            file_name=file_name,
            content=content,
            period=period_date,
            apply=False,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"preview-{uuid.uuid4()}",
        )
        return result.model_dump(mode="json", by_alias=True)
    if idempotency_key is None or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(
            status_code=422,
            detail=(
                "An Idempotency-Key between 16 and 128 characters is required "
                "to register bank payments"
            ),
        )

    async def register_matches() -> tuple[str, dict[str, object]]:
        result = await bank_reconciliation.import_bank_statement(
            session,
            context=context,
            file_name=file_name,
            content=content,
            period=period_date,
            apply=True,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
        )
        return str(context.tenant_id), result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="receivables.bank_statement.register",
        idempotency_key=idempotency_key,
        request_payload={
            "file_name": file_name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "period": period,
        },
        action="receivable.bank_statement_registered",
        entity_type="receivable_batch",
        callback=register_matches,
    )


@router.post(
    "/receivables/{receivable_id}/retention-preview",
    response_model=RetentionXmlPreviewRead,
)
async def post_retention_xml_preview(
    receivable_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("receivables:write"))],
) -> dict[str, object]:
    """Lee un XML de retención SRI antes de registrar el cobro.

    El archivo se procesa solo en memoria. Este endpoint no crea movimientos,
    no adjunta el XML y no sustituye la confirmación humana de ``/payments``.
    """
    xml_bytes = await file.read(receivables.MAX_RETENTION_XML_BYTES + 1)
    preview = await receivables.preview_retention_xml(
        session,
        context=context,
        receivable_id=receivable_id,
        xml_bytes=xml_bytes,
    )
    return preview.model_dump(mode="json", by_alias=True)


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

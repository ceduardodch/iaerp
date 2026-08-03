import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.models.billing import SalesDocument
from app.models.crm import Lead
from app.models.legal_commercial import (
    AwsConsumptionCut,
    BillingProposal,
    CommercialContract,
    ContractVersion,
)
from app.models.masters import EmissionPoint, Establishment, Party, Product, TaxCategory
from app.schemas.billing import (
    InstallmentInput,
    InvoiceInput,
    InvoiceLineInput,
    InvoicePreviewInput,
)
from app.schemas.legal_commercial import (
    AwsConsumptionCutCreate,
    BillingProposalCreate,
    CommercialContractCreate,
    ContractBillingPrepare,
    ContractEmailSend,
    ContractEmailSyncRead,
    ContractVersionCreate,
)
from app.services import billing, crm_integrations, storage

MAX_SIGNED_CONTRACT_BYTES = 10 * 1024 * 1024
MAX_REPORT_BYTES = 15 * 1024 * 1024


async def _customer(session: AsyncSession, context: AuthContext, party_id: uuid.UUID) -> None:
    party = await session.scalar(
        select(Party).where(
            Party.id == party_id, Party.tenant_id == context.tenant_id, Party.active.is_(True)
        )
    )
    if party is None or "CUSTOMER" not in party.roles:
        raise HTTPException(status_code=404, detail="Customer not found")


async def create_contract(
    session: AsyncSession, context: AuthContext, data: CommercialContractCreate
) -> CommercialContract:
    await _customer(session, context, data.party_id)
    if data.source_lead_id is not None:
        lead = await session.scalar(
            select(Lead).where(
                Lead.id == data.source_lead_id,
                Lead.tenant_id == context.tenant_id,
                Lead.party_id == data.party_id,
                Lead.status == "WON",
            )
        )
        if lead is None:
            raise HTTPException(
                status_code=422, detail="A won opportunity for this customer is required"
            )
    if data.service_type == "ACCESSORY" and data.parent_contract_id is None:
        raise HTTPException(
            status_code=422,
            detail="An accessory document requires a parent contract",
        )
    if data.parent_contract_id is not None:
        parent = await session.scalar(
            select(CommercialContract).where(
                CommercialContract.id == data.parent_contract_id,
                CommercialContract.tenant_id == context.tenant_id,
                CommercialContract.party_id == data.party_id,
            )
        )
        if parent is None or parent.service_type == "ACCESSORY":
            raise HTTPException(status_code=404, detail="Parent commercial contract not found")
        if data.service_type != "ACCESSORY":
            raise HTTPException(
                status_code=422, detail="Only accessory documents use a parent contract"
            )
    entity = CommercialContract(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def create_contract_version(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID, data: ContractVersionCreate
) -> ContractVersion:
    contract = await session.scalar(
        select(CommercialContract)
        .where(
            CommercialContract.id == contract_id, CommercialContract.tenant_id == context.tenant_id
        )
        .with_for_update()
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Commercial contract not found")
    if contract.service_type not in {"ACCESSORY", "ONE_OFF"} and not data.pricing_rules:
        raise HTTPException(status_code=422, detail="This service requires a billing rule")
    if data.amends_version_id is not None:
        amended = await session.scalar(
            select(ContractVersion.id).where(
                ContractVersion.id == data.amends_version_id,
                ContractVersion.contract_id == contract_id,
                ContractVersion.tenant_id == context.tenant_id,
            )
        )
        if amended is None:
            raise HTTPException(status_code=404, detail="Amended contract version not found")
    latest = await session.scalar(
        select(ContractVersion.version_number)
        .where(
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
        .order_by(ContractVersion.version_number.desc())
        .limit(1)
    )
    entity = ContractVersion(
        tenant_id=context.tenant_id,
        contract_id=contract_id,
        version_number=(latest or 0) + 1,
        **data.model_dump(by_alias=False),
    )
    session.add(entity)
    await session.flush()
    return entity


async def list_contracts(
    session: AsyncSession, context: AuthContext, party_id: uuid.UUID | None = None
) -> list[CommercialContract]:
    statement = select(CommercialContract).where(CommercialContract.tenant_id == context.tenant_id)
    if party_id is not None:
        statement = statement.where(CommercialContract.party_id == party_id)
    return list(await session.scalars(statement.order_by(CommercialContract.created_at.desc())))


async def list_contract_versions(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID
) -> list[ContractVersion]:
    await _contract(session, context, contract_id)
    return list(
        await session.scalars(
            select(ContractVersion)
            .where(
                ContractVersion.tenant_id == context.tenant_id,
                ContractVersion.contract_id == contract_id,
            )
            .order_by(ContractVersion.version_number.desc())
        )
    )


async def _contract(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID
) -> CommercialContract:
    contract = await session.scalar(
        select(CommercialContract).where(
            CommercialContract.id == contract_id, CommercialContract.tenant_id == context.tenant_id
        )
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Commercial contract not found")
    return contract


async def upload_signed_contract(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    filename: str | None,
    data: bytes,
) -> ContractVersion:
    _validate_pdf(data, max_bytes=MAX_SIGNED_CONTRACT_BYTES, label="Signed contract")
    version = await session.scalar(
        select(ContractVersion)
        .where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Contract version not found")
    if version.signed_artifact_object_key or version.status in {
        "SIGNED",
        "ACTIVE",
        "SUPERSEDED",
        "CANCELLED",
    }:
        raise HTTPException(status_code=409, detail="Signed contract version is immutable")
    safe_name = (filename or "contrato-firmado.pdf").replace("/", "_").replace("\\", "_")
    object_key = (
        f"{context.tenant_id}/commercial/contracts/{contract_id}/"
        f"v{version.version_number}/{safe_name}"
    )
    uploaded = await storage.upload_private_object(
        object_key=object_key, data=data, content_type="application/pdf"
    )
    version.signed_artifact_object_key = uploaded.object_key
    version.signed_artifact_sha256 = uploaded.sha256
    version.signed_artifact_file_name = safe_name
    precheck_status, precheck_details = technical_signature_precheck(data)
    version.signature_precheck_status = precheck_status
    version.signature_precheck_details = precheck_details
    version.status = "PENDING_SIGNATURE"
    contract = await _contract(session, context, contract_id)
    contract.status = "PENDING_SIGNATURE"
    await session.flush()
    return version


def _validate_pdf(data: bytes, *, max_bytes: int, label: str) -> None:
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise HTTPException(status_code=422, detail=f"{label} must be a complete PDF")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{label} exceeds the size limit")


def technical_signature_precheck(data: bytes) -> tuple[str, dict[str, Any]]:
    """Busca estructuras de firma PDF. No valida identidad ni reemplaza FirmaEC."""
    try:
        byte_ranges = data.count(b"/ByteRange")
        signature_types = data.count(b"/Type /Sig") + data.count(b"/Type/Sig")
        subfilters = data.count(b"/SubFilter")
        signature_count = max(byte_ranges, signature_types, subfilters)
        status = "SIGNATURE_FOUND" if signature_count > 0 else "SIGNATURE_NOT_FOUND"
        return status, {
            "signature_count": signature_count,
            "byte_range_markers": byte_ranges,
            "note": "Technical precheck only; validate the document in FirmaEC.",
        }
    except (TypeError, ValueError) as exc:
        return "CHECK_FAILED", {"error": type(exc).__name__}


async def upload_sent_contract(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    filename: str | None,
    data: bytes,
) -> ContractVersion:
    _validate_pdf(data, max_bytes=MAX_SIGNED_CONTRACT_BYTES, label="Contract")
    version = await _version_for_update(session, context, contract_id, version_id)
    if version.status != "DRAFT" or version.sent_artifact_object_key:
        raise HTTPException(status_code=409, detail="A sent contract version is immutable")
    safe_name = (filename or "contrato.pdf").replace("/", "_").replace("\\", "_")
    uploaded = await storage.upload_private_object(
        object_key=(
            f"{context.tenant_id}/commercial/contracts/{contract_id}/"
            f"v{version.version_number}/sent-{safe_name}"
        ),
        data=data,
        content_type="application/pdf",
    )
    version.sent_artifact_object_key = uploaded.object_key
    version.sent_artifact_sha256 = uploaded.sha256
    version.sent_artifact_file_name = safe_name
    await session.flush()
    return version


async def _version_for_update(
    session: AsyncSession,
    context: AuthContext,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ContractVersion:
    version = await session.scalar(
        select(ContractVersion)
        .where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Contract version not found")
    return version


async def send_contract_email(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ContractEmailSend,
) -> ContractVersion:
    contract = await _contract(session, context, contract_id)
    version = await _version_for_update(session, context, contract_id, version_id)
    if version.status != "DRAFT" or not version.sent_artifact_object_key:
        raise HTTPException(status_code=409, detail="Upload a draft PDF before sending it")
    party = await session.scalar(
        select(Party).where(
            Party.id == contract.party_id,
            Party.tenant_id == context.tenant_id,
            Party.active.is_(True),
        )
    )
    if party is None or not party.email:
        raise HTTPException(status_code=422, detail="Customer email is required")
    pdf = await storage.download_artifact(object_key=version.sent_artifact_object_key)
    sent = await crm_integrations.send_google_email_with_thread(
        session,
        context,
        recipient=party.email,
        subject=data.subject,
        message=data.message,
        attachments=[(version.sent_artifact_file_name or "contrato.pdf", "application/pdf", pdf)],
    )
    now = datetime.now(UTC)
    version.gmail_message_id = sent.message_id
    version.gmail_thread_id = sent.thread_id
    version.sent_at = now
    version.status = "PENDING_SIGNATURE"
    contract.status = "PENDING_SIGNATURE"
    await session.flush()
    return version


async def sync_contract_email(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ContractEmailSyncRead:
    contract = await _contract(session, context, contract_id)
    version = await _version_for_update(session, context, contract_id, version_id)
    if not version.gmail_thread_id or not version.gmail_message_id:
        raise HTTPException(status_code=422, detail="This contract has no Gmail thread")
    party = await session.scalar(
        select(Party).where(
            Party.id == contract.party_id,
            Party.tenant_id == context.tenant_id,
        )
    )
    if party is None or not party.email:
        raise HTTPException(status_code=422, detail="Customer email is required")
    checked, message_senders, pdfs = await crm_integrations.google_thread_pdfs(
        session,
        context,
        thread_id=version.gmail_thread_id,
        max_bytes=MAX_SIGNED_CONTRACT_BYTES,
    )
    customer_email = party.email.strip().lower()
    replies = [
        message_id
        for message_id, sender in message_senders
        if message_id != version.gmail_message_id and sender == customer_email
    ]
    reply_detected = bool(replies)
    duplicate_ignored = bool(version.reply_message_id and version.reply_message_id in replies)
    received = False
    candidates = [
        item
        for item in pdfs
        if item.message_id != version.gmail_message_id and item.sender == customer_email
    ]
    if candidates and not version.signed_artifact_object_key:
        candidate = candidates[-1]
        await upload_signed_contract(
            session,
            context,
            contract_id=contract_id,
            version_id=version_id,
            filename=candidate.file_name,
            data=candidate.data,
        )
        version.reply_message_id = candidate.message_id
        received = True
    if reply_detected:
        version.reply_detected_at = version.reply_detected_at or datetime.now(UTC)
        version.reply_message_id = version.reply_message_id or replies[-1]
    await session.flush()
    return ContractEmailSyncRead(
        messages_checked=checked,
        reply_detected=reply_detected,
        signed_pdf_received=received,
        duplicate_ignored=duplicate_ignored,
    )


async def confirm_firmaec(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ContractVersion:
    contract = await _contract(session, context, contract_id)
    version = await _version_for_update(session, context, contract_id, version_id)
    if not version.signed_artifact_object_key:
        raise HTTPException(status_code=422, detail="Upload the signed PDF first")
    if version.status in {"ACTIVE", "SUPERSEDED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Contract version is immutable")
    now = datetime.now(UTC)
    version.firmaec_confirmed_at = now
    version.firmaec_confirmed_by = context.actor_id
    version.signed_at = now
    version.status = "SIGNED"
    contract.status = "SIGNED"
    contract.current_version_id = version.id
    await session.flush()
    return version


async def activate_contract(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ContractVersion:
    contract = await _contract(session, context, contract_id)
    version = await _version_for_update(session, context, contract_id, version_id)
    today = today_in_fiscal_timezone()
    if version.status != "SIGNED" or version.firmaec_confirmed_at is None:
        raise HTTPException(status_code=422, detail="Confirm the signed PDF in FirmaEC first")
    if version.valid_to is not None and version.valid_to < today:
        version.status = "EXPIRED"
        contract.status = "EXPIRED"
        await session.flush()
        raise HTTPException(status_code=422, detail="An expired contract cannot be activated")
    if version.valid_from > today:
        raise HTTPException(status_code=422, detail="The contract validity has not started")
    previous_versions = list(
        await session.scalars(
            select(ContractVersion).where(
                ContractVersion.tenant_id == context.tenant_id,
                ContractVersion.contract_id == contract.id,
                ContractVersion.id != version.id,
                ContractVersion.status == "ACTIVE",
            )
        )
    )
    for previous in previous_versions:
        previous.status = "SUPERSEDED"
    version.status = "ACTIVE"
    contract.status = "ACTIVE"
    contract.current_version_id = version.id
    await session.flush()
    return version


async def signed_contract_download(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    inline: bool = False,
) -> tuple[str, str]:
    version = await session.scalar(
        select(ContractVersion).where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
    )
    if version is None or not version.signed_artifact_object_key:
        raise HTTPException(status_code=404, detail="Signed contract PDF not found")
    file_name = (
        version.signed_artifact_file_name or f"contrato-{contract_id}-v{version.version_number}.pdf"
    )
    return (
        await storage.generate_presigned_download_url(
            object_key=version.signed_artifact_object_key,
            file_name=file_name,
            content_type="application/pdf",
            content_disposition="inline" if inline else "attachment",
        ),
        file_name,
    )


async def sent_contract_download(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    inline: bool = False,
) -> tuple[str, str]:
    version = await session.scalar(
        select(ContractVersion).where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
    )
    if version is None or not version.sent_artifact_object_key:
        raise HTTPException(status_code=404, detail="Contract PDF not found")
    file_name = (
        version.sent_artifact_file_name or f"contrato-{contract_id}-v{version.version_number}.pdf"
    )
    return (
        await storage.generate_presigned_download_url(
            object_key=version.sent_artifact_object_key,
            file_name=file_name,
            content_type="application/pdf",
            content_disposition="inline" if inline else "attachment",
        ),
        file_name,
    )


async def create_aws_cut(
    session: AsyncSession, context: AuthContext, data: AwsConsumptionCutCreate
) -> AwsConsumptionCut:
    await _customer(session, context, data.party_id)
    entity = AwsConsumptionCut(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def list_aws_cuts(
    session: AsyncSession,
    context: AuthContext,
    *,
    party_id: uuid.UUID | None = None,
) -> list[AwsConsumptionCut]:
    statement = select(AwsConsumptionCut).where(AwsConsumptionCut.tenant_id == context.tenant_id)
    if party_id is not None:
        statement = statement.where(AwsConsumptionCut.party_id == party_id)
    return list(await session.scalars(statement.order_by(AwsConsumptionCut.created_at.desc())))


async def upload_aws_evidence(
    session: AsyncSession,
    context: AuthContext,
    *,
    cut_id: uuid.UUID,
    filename: str | None,
    data: bytes,
) -> AwsConsumptionCut:
    if len(data) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="AWS report exceeds 15 MB")
    content_type = _validate_aws_report(filename, data)
    cut = await session.scalar(
        select(AwsConsumptionCut)
        .where(
            AwsConsumptionCut.id == cut_id,
            AwsConsumptionCut.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if cut is None:
        raise HTTPException(status_code=404, detail="AWS consumption cut not found")
    if cut.status in {"REVIEWED", "BILLED"}:
        raise HTTPException(status_code=409, detail="A reviewed AWS cut is immutable")
    safe_name = (filename or "streamone-report").replace("/", "_").replace("\\", "_")
    uploaded = await storage.upload_private_object(
        object_key=f"{context.tenant_id}/commercial/aws/{cut.id}/{safe_name}",
        data=data,
        content_type=content_type,
    )
    cut.evidence_object_key = uploaded.object_key
    cut.evidence_sha256 = uploaded.sha256
    cut.status = "RECONCILED"
    await session.flush()
    return cut


def _validate_aws_report(filename: str | None, data: bytes) -> str:
    safe_name = (filename or "").lower()
    if safe_name.endswith(".pdf"):
        _validate_pdf(data, max_bytes=MAX_REPORT_BYTES, label="AWS report")
        return "application/pdf"
    if safe_name.endswith(".xlsx") and data.startswith(b"PK"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if safe_name.endswith(".xls") and data.startswith(b"\xd0\xcf\x11\xe0"):
        return "application/vnd.ms-excel"
    if safe_name.endswith(".csv"):
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="AWS CSV must use UTF-8") from exc
        if b"\x00" not in data:
            return "text/csv"
    raise HTTPException(
        status_code=422,
        detail="AWS report must be a valid CSV, XLS, XLSX or PDF",
    )


async def confirm_aws_cut(
    session: AsyncSession, context: AuthContext, cut_id: uuid.UUID
) -> AwsConsumptionCut:
    cut = await session.scalar(
        select(AwsConsumptionCut)
        .where(
            AwsConsumptionCut.id == cut_id,
            AwsConsumptionCut.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if cut is None:
        raise HTTPException(status_code=404, detail="AWS consumption cut not found")
    if not cut.evidence_object_key:
        raise HTTPException(status_code=422, detail="Upload the private StreamOne report first")
    if cut.status != "BILLED":
        cut.status = "REVIEWED"
    await session.flush()
    return cut


async def create_billing_proposal(
    session: AsyncSession, context: AuthContext, data: BillingProposalCreate
) -> BillingProposal:
    await _customer(session, context, data.party_id)
    if data.contract_version_id is None and not data.exception_reason:
        raise HTTPException(
            status_code=422, detail="A contract version or documented exception is required"
        )
    if data.contract_version_id is not None:
        version = await session.scalar(
            select(ContractVersion)
            .join(CommercialContract, ContractVersion.contract_id == CommercialContract.id)
            .where(
                ContractVersion.id == data.contract_version_id,
                ContractVersion.tenant_id == context.tenant_id,
                CommercialContract.party_id == data.party_id,
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Contract version not found")
    if data.aws_consumption_cut_id is not None:
        cut = await session.scalar(
            select(AwsConsumptionCut).where(
                AwsConsumptionCut.id == data.aws_consumption_cut_id,
                AwsConsumptionCut.tenant_id == context.tenant_id,
                AwsConsumptionCut.party_id == data.party_id,
                AwsConsumptionCut.status.in_(["RECONCILED", "REVIEWED"]),
            )
        )
        if cut is None:
            raise HTTPException(
                status_code=422, detail="A reconciled AWS consumption cut is required"
            )
    entity = BillingProposal(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


def _rule_value(rule: dict[str, Any], camel: str, snake: str | None = None) -> Any:
    return rule.get(camel, rule.get(snake or camel))


def _money(value: Any, *, field: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field}") from exc
    if amount < 0:
        raise HTTPException(status_code=422, detail=f"{field} cannot be negative")
    return amount


async def prepare_contract_billing(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    data: ContractBillingPrepare,
) -> BillingProposal:
    contract = await _contract(session, context, contract_id)
    if contract.status != "ACTIVE" or contract.current_version_id is None:
        raise HTTPException(status_code=422, detail="Only an active contract can prepare billing")
    version = await session.scalar(
        select(ContractVersion).where(
            ContractVersion.id == contract.current_version_id,
            ContractVersion.contract_id == contract.id,
            ContractVersion.tenant_id == context.tenant_id,
        )
    )
    if version is None or version.status != "ACTIVE":
        raise HTTPException(status_code=422, detail="Active contract version not found")
    if data.period_start < version.valid_from or (
        version.valid_to is not None and version.valid_to < data.period_end
    ):
        raise HTTPException(status_code=422, detail="Billing period is outside contract validity")
    if data.pricing_rule_index >= len(version.pricing_rules):
        raise HTTPException(status_code=422, detail="Billing rule not found")
    existing = await session.scalar(
        select(BillingProposal.id).where(
            BillingProposal.tenant_id == context.tenant_id,
            BillingProposal.contract_version_id == version.id,
            BillingProposal.period_start == data.period_start,
            BillingProposal.period_end == data.period_end,
            BillingProposal.pricing_rule_index == data.pricing_rule_index,
            BillingProposal.status.in_(["READY_FOR_REVIEW", "CONVERTED"]),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Billing is already prepared for this period")

    rule = version.pricing_rules[data.pricing_rule_index]
    if not isinstance(rule, dict):
        raise HTTPException(status_code=422, detail="Invalid billing rule")
    billing_type = contract.service_type
    cut: AwsConsumptionCut | None = None
    if billing_type == "AWS_MONTHLY":
        if data.aws_consumption_cut_id is None or data.manual_total is None:
            raise HTTPException(
                status_code=422, detail="AWS requires a reviewed cut and manual total"
            )
        cut = await session.scalar(
            select(AwsConsumptionCut).where(
                AwsConsumptionCut.id == data.aws_consumption_cut_id,
                AwsConsumptionCut.tenant_id == context.tenant_id,
                AwsConsumptionCut.party_id == contract.party_id,
                AwsConsumptionCut.period_start == data.period_start,
                AwsConsumptionCut.period_end == data.period_end,
                AwsConsumptionCut.status == "REVIEWED",
            )
        )
        if cut is None or cut.total_cost != data.manual_total:
            raise HTTPException(
                status_code=422, detail="Manual AWS total must match the reviewed cut"
            )
        total = cut.total_cost
    elif billing_type == "FIXED_MONTHLY":
        total = _money(_rule_value(rule, "amount"), field="fixed amount")
    elif billing_type == "MILESTONE":
        if _rule_value(rule, "amount") is not None:
            total = _money(_rule_value(rule, "amount"), field="milestone amount")
        else:
            base = _money(_rule_value(rule, "baseAmount", "base_amount"), field="milestone base")
            percentage = _money(_rule_value(rule, "percentage"), field="milestone percentage")
            if percentage > 100:
                raise HTTPException(
                    status_code=422, detail="Milestone percentage cannot exceed 100"
                )
            total = (base * percentage / Decimal("100")).quantize(Decimal("0.01"))
    else:
        total = data.manual_total or _money(_rule_value(rule, "amount"), field="amount")

    establishment_id = _required_uuid(rule, "establishmentId", "establishment_id")
    emission_point_id = _required_uuid(rule, "emissionPointId", "emission_point_id")
    product_id = _required_uuid(rule, "productId", "product_id")
    tax_code = str(_rule_value(rule, "taxCode", "tax_code") or "")
    description = str(_rule_value(rule, "description") or contract.title).strip()
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.id == establishment_id,
            Establishment.tenant_id == context.tenant_id,
            Establishment.active.is_(True),
        )
    )
    emission_point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.id == emission_point_id,
            EmissionPoint.tenant_id == context.tenant_id,
            EmissionPoint.establishment_id == establishment_id,
            EmissionPoint.active.is_(True),
        )
    )
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == context.tenant_id,
            Product.active.is_(True),
        )
    )
    tax = (
        await session.scalar(
            select(TaxCategory).where(
                TaxCategory.id == product.tax_category_id,
                TaxCategory.tenant_id == context.tenant_id,
                TaxCategory.sri_code == tax_code,
            )
        )
        if product is not None and tax_code
        else None
    )
    if establishment is None or emission_point is None or product is None or tax is None:
        raise HTTPException(
            status_code=422, detail="Billing rule has invalid invoice configuration"
        )
    snapshot = {
        "contract_id": str(contract.id),
        "contract_version_id": str(version.id),
        "contract_number": contract.contract_number,
        "period_start": data.period_start.isoformat(),
        "period_end": data.period_end.isoformat(),
        "billing_type": billing_type,
        "establishment_id": str(establishment.id),
        "emission_point_id": str(emission_point.id),
        "product_id": str(product.id),
        "tax_code": tax.sri_code,
        "description": description,
        "payment_terms_days": version.payment_terms_days,
        "amount": str(total),
        "report_required": contract.report_required,
        "collection_enabled": contract.collection_enabled,
    }
    entity = BillingProposal(
        tenant_id=context.tenant_id,
        party_id=contract.party_id,
        contract_version_id=version.id,
        aws_consumption_cut_id=cut.id if cut else None,
        issue_date=today_in_fiscal_timezone(),
        period_start=data.period_start,
        period_end=data.period_end,
        pricing_rule_index=data.pricing_rule_index,
        billing_type=billing_type,
        status="READY_FOR_REVIEW",
        currency="USD",
        total_amount=total,
        commercial_snapshot=snapshot,
        exception_reason=None,
        report_required=contract.report_required,
        collection_enabled=contract.collection_enabled,
    )
    session.add(entity)
    await session.flush()
    return entity


def _required_uuid(rule: dict[str, Any], camel: str, snake: str) -> uuid.UUID:
    value = _rule_value(rule, camel, snake)
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=f"Billing rule requires {camel}") from exc


async def list_billing_proposals(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID | None = None,
) -> list[BillingProposal]:
    statement = select(BillingProposal).where(BillingProposal.tenant_id == context.tenant_id)
    if contract_id is not None:
        statement = statement.join(
            ContractVersion,
            BillingProposal.contract_version_id == ContractVersion.id,
        ).where(ContractVersion.contract_id == contract_id)
    return list(await session.scalars(statement.order_by(BillingProposal.created_at.desc())))


async def upload_billing_report(
    session: AsyncSession,
    context: AuthContext,
    *,
    proposal_id: uuid.UUID,
    filename: str | None,
    data: bytes,
) -> BillingProposal:
    _validate_pdf(data, max_bytes=MAX_REPORT_BYTES, label="Monthly report")
    proposal = await _proposal_for_update(session, context, proposal_id)
    if proposal.status == "CANCELLED" or proposal.report_approved_at is not None:
        raise HTTPException(status_code=409, detail="An approved report is immutable")
    safe_name = (filename or "informe-mensual.pdf").replace("/", "_").replace("\\", "_")
    uploaded = await storage.upload_private_object(
        object_key=f"{context.tenant_id}/commercial/billing/{proposal.id}/{safe_name}",
        data=data,
        content_type="application/pdf",
    )
    proposal.report_object_key = uploaded.object_key
    proposal.report_sha256 = uploaded.sha256
    proposal.report_file_name = safe_name
    await session.flush()
    return proposal


async def approve_billing_report(
    session: AsyncSession, context: AuthContext, proposal_id: uuid.UUID
) -> BillingProposal:
    proposal = await _proposal_for_update(session, context, proposal_id)
    if not proposal.report_object_key:
        raise HTTPException(status_code=422, detail="Upload the monthly report first")
    proposal.report_approved_at = datetime.now(UTC)
    proposal.report_approved_by = context.actor_id
    await session.flush()
    return proposal


async def _proposal_for_update(
    session: AsyncSession, context: AuthContext, proposal_id: uuid.UUID
) -> BillingProposal:
    proposal = await session.scalar(
        select(BillingProposal)
        .where(
            BillingProposal.id == proposal_id,
            BillingProposal.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if proposal is None:
        raise HTTPException(status_code=404, detail="Billing proposal not found")
    return proposal


async def convert_billing_proposal(
    session: AsyncSession, context: AuthContext, proposal_id: uuid.UUID
) -> tuple[BillingProposal, SalesDocument]:
    proposal = await _proposal_for_update(session, context, proposal_id)
    if proposal.status != "READY_FOR_REVIEW" or proposal.sales_document_id is not None:
        raise HTTPException(status_code=409, detail="Billing proposal was already converted")
    snapshot = proposal.commercial_snapshot
    issue_date = today_in_fiscal_timezone()
    payment_terms = int(snapshot.get("payment_terms_days", 0))
    invoice_line = InvoiceLineInput(
        product_id=uuid.UUID(str(snapshot["product_id"])),
        description=str(snapshot["description"]),
        quantity=Decimal("1"),
        unit_price=proposal.total_amount,
        discount=Decimal("0"),
        tax_code=str(snapshot["tax_code"]),
    )
    preview = await billing.preview_invoice(
        session,
        context,
        InvoicePreviewInput(issue_date=issue_date, lines=[invoice_line]),
    )
    invoice = await billing.create_invoice_draft(
        session,
        context,
        InvoiceInput(
            customer_id=proposal.party_id,
            establishment_id=uuid.UUID(str(snapshot["establishment_id"])),
            emission_point_id=uuid.UUID(str(snapshot["emission_point_id"])),
            issue_date=issue_date,
            installments=[
                InstallmentInput(
                    due_date=issue_date + timedelta(days=payment_terms),
                    amount=preview.total,
                )
            ],
            lines=[invoice_line],
            collection_enabled=proposal.collection_enabled,
        ),
        commercial_snapshot=dict(snapshot),
    )
    proposal.sales_document_id = invoice.id
    proposal.status = "CONVERTED"
    if proposal.aws_consumption_cut_id is not None:
        cut = await session.get(AwsConsumptionCut, proposal.aws_consumption_cut_id)
        if cut is not None and cut.tenant_id == context.tenant_id:
            cut.status = "BILLED"
    await session.flush()
    return proposal, invoice

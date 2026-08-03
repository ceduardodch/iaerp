import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator

from app.schemas.base import APIModel

ContractStatus = Literal[
    "DRAFT", "PENDING_SIGNATURE", "SIGNED", "ACTIVE", "EXPIRED", "SUPERSEDED", "CANCELLED"
]
ServiceType = Literal["FIXED_MONTHLY", "AWS_MONTHLY", "MILESTONE", "ONE_OFF", "ACCESSORY"]
SignaturePrecheckStatus = Literal["SIGNATURE_FOUND", "SIGNATURE_NOT_FOUND", "CHECK_FAILED"]
CutSource = Literal["AWS_COST_EXPLORER", "CSV_UPLOAD", "XLSX_UPLOAD"]
CutStatus = Literal["IMPORTED", "RECONCILED", "REVIEWED", "REJECTED", "BILLED"]


class CommercialContractCreate(APIModel):
    party_id: uuid.UUID
    contract_number: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    service_type: ServiceType = "FIXED_MONTHLY"
    source_lead_id: uuid.UUID | None = None
    parent_contract_id: uuid.UUID | None = None
    report_required: bool = False
    collection_enabled: bool = False


class CommercialContractRead(CommercialContractCreate):
    id: uuid.UUID
    status: ContractStatus
    current_version_id: uuid.UUID | None


class ContractVersionCreate(APIModel):
    valid_from: date
    valid_to: date | None = None
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    renewal_notice_days: int | None = Field(default=None, ge=0, le=365)
    pricing_rules: list[dict[str, Any]] = Field(default_factory=list)
    amends_version_id: uuid.UUID | None = None

    @field_validator("valid_to")
    @classmethod
    def valid_range(cls, value: date | None, info: ValidationInfo) -> date | None:
        if value is not None and (valid_from := info.data.get("valid_from")) and value < valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return value


class ContractVersionRead(ContractVersionCreate):
    id: uuid.UUID
    contract_id: uuid.UUID
    version_number: int
    status: ContractStatus
    signed_at: datetime | None
    sent_at: datetime | None
    sent_artifact_sha256: str | None
    gmail_thread_id: str | None
    reply_detected_at: datetime | None
    signed_artifact_sha256: str | None
    signature_precheck_status: SignaturePrecheckStatus | None
    signature_precheck_details: dict[str, Any] | None
    firmaec_confirmed_at: datetime | None


class ContractArtifactDownloadRead(APIModel):
    """Enlace temporal a un contrato firmado, nunca una URL publica fija."""

    download_url: str
    expires_in_seconds: int
    file_name: str


class ContractEmailSend(APIModel):
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)


class ContractEmailSyncRead(APIModel):
    messages_checked: int
    reply_detected: bool
    signed_pdf_received: bool
    duplicate_ignored: bool


class ContractActionRead(APIModel):
    id: uuid.UUID
    status: ContractStatus


class AwsConsumptionCutCreate(APIModel):
    party_id: uuid.UUID
    period_start: date
    period_end: date
    source: CutSource
    total_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    currency: Literal["USD"] = "USD"
    reconciliation_summary: dict[str, Any] | None = None

    @field_validator("period_end")
    @classmethod
    def valid_period(cls, value: date, info: ValidationInfo) -> date:
        if (period_start := info.data.get("period_start")) and value < period_start:
            raise ValueError("period_end must not be before period_start")
        return value


class AwsConsumptionCutRead(AwsConsumptionCutCreate):
    id: uuid.UUID
    status: CutStatus
    evidence_sha256: str | None


class BillingProposalCreate(APIModel):
    party_id: uuid.UUID
    issue_date: date
    total_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    contract_version_id: uuid.UUID | None = None
    aws_consumption_cut_id: uuid.UUID | None = None
    exception_reason: str | None = Field(default=None, max_length=2000)
    commercial_snapshot: dict[str, Any] = Field(default_factory=dict)
    period_start: date | None = None
    period_end: date | None = None
    pricing_rule_index: int = Field(default=0, ge=0)
    billing_type: ServiceType = "ONE_OFF"
    report_required: bool = False
    collection_enabled: bool = False


class ContractBillingPrepare(APIModel):
    period_start: date
    period_end: date
    pricing_rule_index: int = Field(default=0, ge=0)
    aws_consumption_cut_id: uuid.UUID | None = None
    manual_total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)

    @field_validator("period_end")
    @classmethod
    def valid_billing_period(cls, value: date, info: ValidationInfo) -> date:
        if (period_start := info.data.get("period_start")) and value < period_start:
            raise ValueError("period_end must not be before period_start")
        return value


class BillingProposalRead(BillingProposalCreate):
    id: uuid.UUID
    status: Literal["DRAFT", "READY_FOR_REVIEW", "CONVERTED", "CANCELLED"]
    sales_document_id: uuid.UUID | None
    report_sha256: str | None
    report_file_name: str | None
    report_approved_at: datetime | None

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import APIModel
from app.schemas.masters import AnalyticAssignmentRead
from app.schemas.receivables import PaymentMethod

PayableStatus = Literal["OPEN", "PARTIAL", "SETTLED", "VOIDED"]
TaxClassification = Literal[
    "DEDUCTIBLE_PENDING_REVIEW",
    "DEDUCTIBLE_CONFIRMED",
    "NON_DEDUCTIBLE",
]
InternalClassification = Literal["PENDING_REVIEW", "REAL", "DECLARATION_ONLY"]
EvidenceStatus = Literal["NONE", "ATTACHED", "PRELIMINARY", "FISCAL_XML"]


class PayableInstallmentInput(APIModel):
    due_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class PayableCreate(APIModel):
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = Field(default=None, max_length=300)
    description: str = Field(min_length=2, max_length=500)
    category: str = Field(default="Sin clasificar", min_length=2, max_length=120)
    document_type: Literal["INVOICE", "LIQUIDATION", "DEBIT_NOTE", "OTHER"] = "OTHER"
    document_number: str | None = Field(default=None, max_length=80)
    issue_date: date
    due_date: date | None = None
    installments: list[PayableInstallmentInput] = Field(default_factory=list)
    total: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    tax_classification: TaxClassification = "DEDUCTIBLE_PENDING_REVIEW"
    internal_classification: InternalClassification = "PENDING_REVIEW"
    evidence_status: EvidenceStatus = "NONE"
    support_reference: str | None = Field(default=None, max_length=300)
    payment_timing: Literal["PAID_NOW", "PAY_LATER"] = "PAY_LATER"
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None
    payment_reference: str | None = Field(default=None, max_length=300)
    analytic_value_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_plan(self) -> PayableCreate:
        if self.installments:
            installment_total = sum((item.amount for item in self.installments), Decimal("0.00"))
            if installment_total != self.total:
                raise ValueError("Installments must add up to the payable total")
        if self.payment_timing == "PAID_NOW" and self.installments:
            raise ValueError("Paid-now expenses cannot define future installments")
        return self


class PayableFromDocumentCreate(APIModel):
    document_id: uuid.UUID


class PayableDocumentReviewCreate(APIModel):
    document_id: uuid.UUID
    tax_classification: Literal["DEDUCTIBLE_CONFIRMED", "NON_DEDUCTIBLE"]
    internal_classification: InternalClassification = "PENDING_REVIEW"
    analytic_value_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    payment_state: Literal["PAID", "SCHEDULED", "UNCONFIRMED", "KEEP_EXISTING"]
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None
    payment_reference: str | None = Field(default=None, max_length=300)
    scheduled_date: date | None = None

    @model_validator(mode="after")
    def validate_review(self) -> PayableDocumentReviewCreate:
        if self.payment_state == "PAID" and self.payment_date is None:
            raise ValueError("paymentDate is required when the expense is already paid")
        if self.payment_state == "SCHEDULED" and self.scheduled_date is None:
            raise ValueError("scheduledDate is required when payment is planned")
        return self


class PayableBulkAnalyticChange(APIModel):
    mode: Literal["KEEP_EXISTING", "APPLY"] = "KEEP_EXISTING"
    value_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class PayableDocumentBulkReviewCreate(APIModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    tax_classification: Literal["DEDUCTIBLE_CONFIRMED", "NON_DEDUCTIBLE"]
    internal_classification: InternalClassification = "PENDING_REVIEW"
    analytic_change: PayableBulkAnalyticChange = Field(default_factory=PayableBulkAnalyticChange)
    payment_action: Literal["KEEP_EXISTING_OR_UNCONFIRMED", "PAID", "SCHEDULED"] = (
        "KEEP_EXISTING_OR_UNCONFIRMED"
    )
    payment_date: date | None = None
    payment_method: PaymentMethod | None = None
    payment_reference: str | None = Field(default=None, max_length=300)
    scheduled_date: date | None = None

    @model_validator(mode="after")
    def validate_bulk_review(self) -> PayableDocumentBulkReviewCreate:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("documentIds must be unique")
        if self.analytic_change.mode == "APPLY" and not self.analytic_change.value_ids:
            raise ValueError("Select at least one tag when applying bulk tags")
        if self.payment_action == "PAID":
            if self.payment_date is None or self.payment_method is None:
                raise ValueError(
                    "paymentDate and paymentMethod are required when marking purchases paid"
                )
        if self.payment_action == "SCHEDULED" and self.scheduled_date is None:
            raise ValueError("scheduledDate is required when payment is planned")
        return self


class PayableDocumentBulkReviewItemRead(APIModel):
    document_id: uuid.UUID
    payable_id: uuid.UUID | None = None
    status: Literal["REVIEWED", "PROTECTED", "SKIPPED", "FAILED"]
    detail: str


class PayableDocumentBulkReviewRead(APIModel):
    reviewed_count: int = Field(ge=0)
    protected_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    items: list[PayableDocumentBulkReviewItemRead]


class PayableClassificationUpdate(APIModel):
    tax_classification: Literal["DEDUCTIBLE_CONFIRMED", "NON_DEDUCTIBLE"]
    internal_classification: Literal["REAL", "DECLARATION_ONLY"] | None = None
    reason: str | None = Field(default=None, min_length=3, max_length=300)
    analytic_value_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class PayablePaymentCreate(APIModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payment_date: date
    method: PaymentMethod | None = None
    reference: str | None = Field(default=None, max_length=300)


class PayableAdjustmentCreate(APIModel):
    movement_type: Literal["RETENTION", "CREDIT_NOTE"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    effective_date: date
    reference: str = Field(min_length=3, max_length=300)


class PayableReversalCreate(APIModel):
    reason: str = Field(min_length=3, max_length=300)
    effective_date: date


class PaymentScheduleCreate(APIModel):
    scheduled_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"


class PayableRead(APIModel):
    id: uuid.UUID
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    fiscal_document_id: uuid.UUID | None
    description: str
    category: str
    document_type: str
    document_number: str | None
    issue_date: date
    due_date: date | None
    total: Decimal
    open_amount: Decimal
    currency: Literal["USD"] = "USD"
    status: PayableStatus
    tax_classification: TaxClassification
    internal_classification: InternalClassification
    evidence_status: EvidenceStatus
    support_reference: str | None
    analytic_assignments: list[AnalyticAssignmentRead] = Field(default_factory=list)


class PayableMovementRead(APIModel):
    id: uuid.UUID
    payable_id: uuid.UUID
    installment_id: uuid.UUID
    movement_type: Literal["PAYMENT", "RETENTION", "CREDIT_NOTE", "REVERSAL"]
    amount: Decimal
    effective_date: date
    method: PaymentMethod | None
    support_reference: str | None
    reversed_movement_id: uuid.UUID | None
    actor_id: str
    created_at: datetime


class PaymentScheduleRead(APIModel):
    id: uuid.UUID
    payable_id: uuid.UUID
    scheduled_date: date
    amount: Decimal
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
    status: str


class ExpenseRuleCreate(APIModel):
    name: str = Field(min_length=2, max_length=120)
    description_pattern: str = Field(min_length=2, max_length=200)
    account_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    amount_min: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    amount_max: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    category: str = Field(min_length=2, max_length=120)
    supplier_name: str | None = Field(default=None, max_length=300)
    tax_classification: TaxClassification = "DEDUCTIBLE_PENDING_REVIEW"
    active: bool = True

    @model_validator(mode="after")
    def validate_amount_range(self) -> ExpenseRuleCreate:
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amountMin cannot be greater than amountMax")
        return self


class ExpenseRuleRead(ExpenseRuleCreate):
    id: uuid.UUID


class BankDebitAllocationInput(APIModel):
    transaction_id: str = Field(min_length=64, max_length=64)
    payable_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)

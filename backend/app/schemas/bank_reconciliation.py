from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import APIModel


class BankStatementMatchRead(APIModel):
    transaction_id: str = Field(min_length=64, max_length=64)
    payment_date: date
    reference: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    receivable_id: uuid.UUID
    invoice_sequential: str = Field(min_length=9, max_length=9)
    original_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    retention_total: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    replaces_manual_payment: bool
    status: Literal["MATCHED", "REGISTERED"]
    detail: str


class BankStatementManualCorrectionRead(APIModel):
    transaction_id: str = Field(min_length=64, max_length=64)
    payment_date: date
    reference: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    target_receivable_id: uuid.UUID
    target_invoice_sequential: str = Field(min_length=9, max_length=9)
    manual_receivable_id: uuid.UUID
    manual_invoice_sequential: str = Field(min_length=9, max_length=9)
    manual_movement_id: uuid.UUID
    status: Literal["CORRECTION_REQUIRED", "CORRECTED"]
    detail: str


class BankStatementDebitMatchRead(APIModel):
    transaction_id: str = Field(min_length=64, max_length=64)
    payment_date: date
    reference: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payable_id: uuid.UUID
    supplier_name: str | None = None
    document_number: str | None = None
    payable_total: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    allocated_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    links_existing_payment: bool = False
    status: Literal["MATCHED", "REGISTERED", "EVIDENCE_LINKED"]
    detail: str


class BankStatementDebitSuggestionRead(APIModel):
    transaction_id: str = Field(min_length=64, max_length=64)
    payment_date: date
    reference: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    classification: Literal[
        "UNCLASSIFIED",
        "EXPENSE_CANDIDATE",
        "BANK_FEE",
        "BANK_TAX",
        "INTERNAL_TRANSFER",
        "CARD_SETTLEMENT",
    ]
    rule_id: uuid.UUID | None = None
    rule_name: str | None = None
    suggested_category: str | None = None
    suggested_supplier_name: str | None = None
    suggested_tax_classification: str | None = None
    detail: str


class BankStatementImportRead(APIModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    file_name: str
    source_sha256: str = Field(min_length=64, max_length=64)
    account_masked: str
    total_rows: int = Field(ge=0)
    credit_rows: int = Field(ge=0)
    debit_rows: int = Field(ge=0)
    outside_period_credit_count: int = Field(ge=0)
    outside_period_debit_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    unmatched_credit_count: int = Field(ge=0)
    ignored_debit_count: int = Field(ge=0)
    payable_matched_count: int = Field(ge=0)
    unmatched_debit_count: int = Field(ge=0)
    rule_suggestion_count: int = Field(ge=0)
    already_imported_count: int = Field(ge=0)
    manual_correction_count: int = Field(ge=0)
    matches: list[BankStatementMatchRead]
    manual_corrections: list[BankStatementManualCorrectionRead]
    debit_matches: list[BankStatementDebitMatchRead]
    debit_suggestions: list[BankStatementDebitSuggestionRead]

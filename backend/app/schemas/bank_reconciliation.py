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


class BankStatementImportRead(APIModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    file_name: str
    source_sha256: str = Field(min_length=64, max_length=64)
    total_rows: int = Field(ge=0)
    credit_rows: int = Field(ge=0)
    outside_period_credit_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    unmatched_credit_count: int = Field(ge=0)
    ignored_debit_count: int = Field(ge=0)
    already_imported_count: int = Field(ge=0)
    matches: list[BankStatementMatchRead]

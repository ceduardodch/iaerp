from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import APIModel


class CollectionInstallment(APIModel):
    id: UUID
    sequence: int
    due_date: date
    open_amount: Decimal


class CollectionAccount(APIModel):
    id: UUID
    party_id: UUID
    customer_name: str
    invoice_number: str
    currency: str
    original_amount: Decimal
    cash_amount: Decimal
    retention_amount: Decimal
    open_amount: Decimal
    due_date: date
    overdue: bool
    installments: list[CollectionInstallment]
    installment_count: int
    promised_date: date | None
    email: str | None
    collection_enabled: bool
    can_enable_reminders: bool
    reminder_blocked_reason: str | None
    last_reminder_at: datetime | None
    last_reminder_status: str | None


class CollectionWrite(APIModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PromiseChange(CollectionWrite):
    promised_date: date | None
    previous_promised_date: date | None


class TermChange(CollectionWrite):
    installment_id: UUID | None = None
    due_date: date
    previous_due_date: date
    reason: str = Field(min_length=3, max_length=500)


class ReminderConfirmation(CollectionWrite):
    expected_recipient: str = Field(min_length=1, max_length=320)
    expected_open_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    expected_due_date: date

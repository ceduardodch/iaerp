from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin


class Payable(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "payables"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_payables_tenant_supplier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_payables_tenant_fiscal_document",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_payables_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "fiscal_document_id",
            name="uq_payables_tenant_fiscal_document",
        ),
        CheckConstraint("total > 0", name="payables_total_positive"),
        CheckConstraint(
            "status IN ('OPEN', 'PARTIALLY_PAID', 'PAID', 'VOID')",
            name="payables_status_valid",
        ),
        CheckConstraint(
            "tax_classification IN ('DEDUCTIBLE_PENDING_REVIEW', "
            "'DEDUCTIBLE_CONFIRMED', 'NON_DEDUCTIBLE')",
            name="payables_tax_classification_valid",
        ),
        CheckConstraint(
            "evidence_status IN ('NONE', 'ATTACHED', 'PRELIMINARY', 'FISCAL_XML')",
            name="payables_evidence_status_valid",
        ),
        Index("ix_payables_tenant_status", "tenant_id", "status"),
        Index("ix_payables_tenant_due_date", "tenant_id", "due_date"),
        Index("ix_payables_tenant_supplier", "tenant_id", "supplier_id"),
    )

    supplier_id: Mapped[uuid.UUID | None]
    supplier_name: Mapped[str | None] = mapped_column(String(300))
    fiscal_document_id: Mapped[uuid.UUID | None]
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(120), default="Sin clasificar")
    document_type: Mapped[str] = mapped_column(String(30), default="OTHER")
    document_number: Mapped[str | None] = mapped_column(String(80))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    tax_classification: Mapped[str] = mapped_column(
        String(40), default="DEDUCTIBLE_PENDING_REVIEW"
    )
    evidence_status: Mapped[str] = mapped_column(String(20), default="NONE")
    support_reference: Mapped[str | None] = mapped_column(String(300))


class PayableInstallment(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "payable_installments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_installments_tenant_payable",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_payable_installments_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "payable_id",
            "sequence",
            name="uq_payable_installments_tenant_payable_sequence",
        ),
        CheckConstraint("amount > 0", name="payable_installments_amount_positive"),
        Index("ix_payable_installments_payable", "tenant_id", "payable_id"),
        Index("ix_payable_installments_due_date", "tenant_id", "due_date"),
    )

    payable_id: Mapped[uuid.UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class PayableMovement(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "payable_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_movements_tenant_payable",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "installment_id"],
            ["payable_installments.tenant_id", "payable_installments.id"],
            name="fk_payable_movements_tenant_installment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reversed_movement_id"],
            ["payable_movements.tenant_id", "payable_movements.id"],
            name="fk_payable_movements_tenant_reversed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_payable_movements_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "reversed_movement_id",
            name="uq_payable_movements_tenant_reversed",
        ),
        CheckConstraint("amount > 0", name="payable_movements_amount_positive"),
        CheckConstraint(
            "movement_type IN ('PAYMENT', 'RETENTION', 'CREDIT_NOTE', 'REVERSAL')",
            name="payable_movements_type_valid",
        ),
        Index("ix_payable_movements_payable", "tenant_id", "payable_id"),
    )

    payable_id: Mapped[uuid.UUID]
    installment_id: Mapped[uuid.UUID]
    movement_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(String(20))
    support_reference: Mapped[str | None] = mapped_column(String(300))
    reversed_movement_id: Mapped[uuid.UUID | None]
    actor_id: Mapped[str] = mapped_column(String(200))


class SupplierPaymentSchedule(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base
):
    __tablename__ = "supplier_payment_schedules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_supplier_payment_schedules_tenant_payable",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_supplier_payment_schedules_tenant_id"
        ),
        CheckConstraint("amount > 0", name="supplier_payment_schedules_amount_positive"),
        CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
            name="supplier_payment_schedules_priority_valid",
        ),
        Index("ix_supplier_payment_schedules_date", "tenant_id", "scheduled_date"),
    )

    payable_id: Mapped[uuid.UUID]
    scheduled_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    priority: Mapped[str] = mapped_column(String(10), default="NORMAL")
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED")


class ExpenseRecognitionRule(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base
):
    __tablename__ = "expense_recognition_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_expense_rules_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_expense_rules_tenant_name"),
        CheckConstraint(
            "amount_min IS NULL OR amount_min >= 0",
            name="expense_rules_amount_min_non_negative",
        ),
        CheckConstraint(
            "amount_max IS NULL OR amount_max >= 0",
            name="expense_rules_amount_max_non_negative",
        ),
        Index("ix_expense_rules_tenant_active", "tenant_id", "active"),
    )

    name: Mapped[str] = mapped_column(String(120))
    description_pattern: Mapped[str] = mapped_column(String(200))
    account_last4: Mapped[str | None] = mapped_column(String(4))
    amount_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    category: Mapped[str] = mapped_column(String(120))
    supplier_name: Mapped[str | None] = mapped_column(String(300))
    tax_classification: Mapped[str] = mapped_column(
        String(40), default="DEDUCTIBLE_PENDING_REVIEW"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class BankStatementImport(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "bank_statement_imports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_bank_statement_imports_tenant_id"),
        UniqueConstraint(
            "tenant_id", "source_sha256", name="uq_bank_statement_imports_tenant_source"
        ),
        Index("ix_bank_statement_imports_tenant_period", "tenant_id", "period"),
    )

    source_sha256: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(255))
    account_masked: Mapped[str] = mapped_column(String(32))
    period: Mapped[date] = mapped_column(Date)
    imported_by: Mapped[str] = mapped_column(String(200))


class BankTransaction(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "statement_import_id"],
            ["bank_statement_imports.tenant_id", "bank_statement_imports.id"],
            name="fk_bank_transactions_tenant_import",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_bank_transactions_tenant_id"),
        UniqueConstraint(
            "tenant_id", "transaction_id", name="uq_bank_transactions_tenant_transaction"
        ),
        CheckConstraint(
            "direction IN ('CREDIT', 'DEBIT')",
            name="bank_transactions_direction_valid",
        ),
        CheckConstraint("amount > 0", name="bank_transactions_amount_positive"),
        Index("ix_bank_transactions_tenant_date", "tenant_id", "occurred_at"),
    )

    statement_import_id: Mapped[uuid.UUID]
    transaction_id: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(10))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    classification: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED")


class BankTransactionAllocation(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base
):
    __tablename__ = "bank_transaction_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "bank_transaction_id"],
            ["bank_transactions.tenant_id", "bank_transactions.id"],
            name="fk_bank_allocations_tenant_transaction",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_bank_allocations_tenant_payable",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_bank_allocations_tenant_receivable",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_bank_allocations_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "bank_transaction_id",
            "payable_id",
            "receivable_id",
            name="uq_bank_allocations_tenant_target",
        ),
        CheckConstraint("amount > 0", name="bank_allocations_amount_positive"),
        CheckConstraint(
            "(payable_id IS NOT NULL AND receivable_id IS NULL) OR "
            "(payable_id IS NULL AND receivable_id IS NOT NULL)",
            name="bank_allocations_one_target",
        ),
        Index("ix_bank_allocations_transaction", "tenant_id", "bank_transaction_id"),
    )

    bank_transaction_id: Mapped[uuid.UUID]
    payable_id: Mapped[uuid.UUID | None]
    receivable_id: Mapped[uuid.UUID | None]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

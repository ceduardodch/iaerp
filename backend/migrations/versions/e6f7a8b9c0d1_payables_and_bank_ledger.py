"""add operational payables and shared bank reconciliation

Revision ID: e6f7a8b9c0d1
Revises: da1e2f3a4b5c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"  # pragma: allowlist secret
down_revision: str | None = "da1e2f3a4b5c"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.create_table(
        "payables",
        sa.Column("supplier_id", sa.Uuid()),
        sa.Column("supplier_name", sa.String(300)),
        sa.Column("fiscal_document_id", sa.Uuid()),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("category", sa.String(120), nullable=False, server_default="Sin clasificar"),
        sa.Column("document_type", sa.String(30), nullable=False, server_default="OTHER"),
        sa.Column("document_number", sa.String(80)),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column(
            "tax_classification",
            sa.String(40),
            nullable=False,
            server_default="DEDUCTIBLE_PENDING_REVIEW",
        ),
        sa.Column("evidence_status", sa.String(20), nullable=False, server_default="NONE"),
        sa.Column("support_reference", sa.String(300)),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("total > 0", name="ck_payables_payables_total_positive"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'PARTIALLY_PAID', 'PAID', 'VOID')",
            name="ck_payables_payables_status_valid",
        ),
        sa.CheckConstraint(
            "tax_classification IN ('DEDUCTIBLE_PENDING_REVIEW', "
            "'DEDUCTIBLE_CONFIRMED', 'NON_DEDUCTIBLE')",
            name="ck_payables_payables_tax_classification_valid",
        ),
        sa.CheckConstraint(
            "evidence_status IN ('NONE', 'ATTACHED', 'PRELIMINARY', 'FISCAL_XML')",
            name="ck_payables_payables_evidence_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_payables_tenant_supplier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_payables_tenant_fiscal_document",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payables_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "fiscal_document_id", name="uq_payables_tenant_fiscal_document"
        ),
    )
    op.create_index("ix_payables_tenant_id", "payables", ["tenant_id"])
    op.create_index("ix_payables_tenant_status", "payables", ["tenant_id", "status"])
    op.create_index("ix_payables_tenant_due_date", "payables", ["tenant_id", "due_date"])
    op.create_index("ix_payables_tenant_supplier", "payables", ["tenant_id", "supplier_id"])

    op.create_table(
        "payable_installments",
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name="ck_payable_installments_payable_installments_amount_positive"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_installments_tenant_payable",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payable_installments_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "payable_id",
            "sequence",
            name="uq_payable_installments_tenant_payable_sequence",
        ),
    )
    op.create_index("ix_payable_installments_tenant_id", "payable_installments", ["tenant_id"])
    op.create_index(
        "ix_payable_installments_payable",
        "payable_installments",
        ["tenant_id", "payable_id"],
    )
    op.create_index(
        "ix_payable_installments_due_date",
        "payable_installments",
        ["tenant_id", "due_date"],
    )

    op.create_table(
        "payable_movements",
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("installment_id", sa.Uuid(), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(20)),
        sa.Column("support_reference", sa.String(300)),
        sa.Column("reversed_movement_id", sa.Uuid()),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount > 0", name="ck_payable_movements_payable_movements_amount_positive"
        ),
        sa.CheckConstraint(
            "movement_type IN ('PAYMENT', 'RETENTION', 'CREDIT_NOTE', 'REVERSAL')",
            name="ck_payable_movements_payable_movements_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_movements_tenant_payable",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "installment_id"],
            ["payable_installments.tenant_id", "payable_installments.id"],
            name="fk_payable_movements_tenant_installment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reversed_movement_id"],
            ["payable_movements.tenant_id", "payable_movements.id"],
            name="fk_payable_movements_tenant_reversed",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payable_movements_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "reversed_movement_id", name="uq_payable_movements_tenant_reversed"
        ),
    )
    op.create_index("ix_payable_movements_tenant_id", "payable_movements", ["tenant_id"])
    op.create_index(
        "ix_payable_movements_payable",
        "payable_movements",
        ["tenant_id", "payable_id"],
    )

    op.create_table(
        "supplier_payment_schedules",
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False, server_default="NORMAL"),
        sa.Column("status", sa.String(20), nullable=False, server_default="SCHEDULED"),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_supplier_payment_schedules_supplier_payment_schedules_amount_positive",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
            name="ck_supplier_payment_schedules_supplier_payment_schedules_priority_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_supplier_payment_schedules_tenant_payable",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_supplier_payment_schedules_tenant_id"
        ),
    )
    op.create_index(
        "ix_supplier_payment_schedules_tenant_id", "supplier_payment_schedules", ["tenant_id"]
    )
    op.create_index(
        "ix_supplier_payment_schedules_date",
        "supplier_payment_schedules",
        ["tenant_id", "scheduled_date"],
    )

    op.create_table(
        "expense_recognition_rules",
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description_pattern", sa.String(200), nullable=False),
        sa.Column("account_last4", sa.String(4)),
        sa.Column("amount_min", sa.Numeric(18, 2)),
        sa.Column("amount_max", sa.Numeric(18, 2)),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("supplier_name", sa.String(300)),
        sa.Column(
            "tax_classification",
            sa.String(40),
            nullable=False,
            server_default="DEDUCTIBLE_PENDING_REVIEW",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount_min IS NULL OR amount_min >= 0",
            name="ck_expense_recognition_rules_expense_rules_amount_min_non_negative",
        ),
        sa.CheckConstraint(
            "amount_max IS NULL OR amount_max >= 0",
            name="ck_expense_recognition_rules_expense_rules_amount_max_non_negative",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_expense_rules_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_expense_rules_tenant_name"),
    )
    op.create_index("ix_expense_recognition_rules_tenant_id", "expense_recognition_rules", ["tenant_id"])
    op.create_index(
        "ix_expense_rules_tenant_active",
        "expense_recognition_rules",
        ["tenant_id", "active"],
    )

    op.create_table(
        "bank_statement_imports",
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("account_masked", sa.String(32), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("imported_by", sa.String(200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_bank_statement_imports_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "source_sha256", name="uq_bank_statement_imports_tenant_source"
        ),
    )
    op.create_index("ix_bank_statement_imports_tenant_id", "bank_statement_imports", ["tenant_id"])
    op.create_index(
        "ix_bank_statement_imports_tenant_period",
        "bank_statement_imports",
        ["tenant_id", "period"],
    )

    op.create_table(
        "bank_transactions",
        sa.Column("statement_import_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False, server_default="UNCLASSIFIED"),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "direction IN ('CREDIT', 'DEBIT')",
            name="ck_bank_transactions_bank_transactions_direction_valid",
        ),
        sa.CheckConstraint(
            "amount > 0", name="ck_bank_transactions_bank_transactions_amount_positive"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "statement_import_id"],
            ["bank_statement_imports.tenant_id", "bank_statement_imports.id"],
            name="fk_bank_transactions_tenant_import",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_bank_transactions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "transaction_id", name="uq_bank_transactions_tenant_transaction"
        ),
    )
    op.create_index("ix_bank_transactions_tenant_id", "bank_transactions", ["tenant_id"])
    op.create_index(
        "ix_bank_transactions_tenant_date", "bank_transactions", ["tenant_id", "occurred_at"]
    )

    op.create_table(
        "bank_transaction_allocations",
        sa.Column("bank_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("payable_id", sa.Uuid()),
        sa.Column("receivable_id", sa.Uuid()),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_bank_transaction_allocations_bank_allocations_amount_positive",
        ),
        sa.CheckConstraint(
            "(payable_id IS NOT NULL AND receivable_id IS NULL) OR "
            "(payable_id IS NULL AND receivable_id IS NOT NULL)",
            name="ck_bank_transaction_allocations_bank_allocations_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bank_transaction_id"],
            ["bank_transactions.tenant_id", "bank_transactions.id"],
            name="fk_bank_allocations_tenant_transaction",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_bank_allocations_tenant_payable",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_bank_allocations_tenant_receivable",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_bank_allocations_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "bank_transaction_id",
            "payable_id",
            "receivable_id",
            name="uq_bank_allocations_tenant_target",
        ),
    )
    op.create_index(
        "ix_bank_transaction_allocations_tenant_id",
        "bank_transaction_allocations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_bank_allocations_transaction",
        "bank_transaction_allocations",
        ["tenant_id", "bank_transaction_id"],
    )


def downgrade() -> None:
    op.drop_table("bank_transaction_allocations")
    op.drop_table("bank_transactions")
    op.drop_table("bank_statement_imports")
    op.drop_table("expense_recognition_rules")
    op.drop_table("supplier_payment_schedules")
    op.drop_table("payable_movements")
    op.drop_table("payable_installments")
    op.drop_table("payables")


"""Simple contract, billing evidence, and collection opt-in flow.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d9e0f1a2b3"  # pragma: allowlist secret
down_revision: str | None = "b7c8d9e0f1a2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commercial_contracts", sa.Column("source_lead_id", postgresql.UUID(), nullable=True)
    )
    op.add_column(
        "commercial_contracts", sa.Column("parent_contract_id", postgresql.UUID(), nullable=True)
    )
    op.add_column(
        "commercial_contracts",
        sa.Column(
            "service_type", sa.String(length=30), nullable=False, server_default="FIXED_MONTHLY"
        ),
    )
    op.add_column(
        "commercial_contracts",
        sa.Column("report_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "commercial_contracts",
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_commercial_contracts_tenant_lead",
        "commercial_contracts",
        "crm_leads",
        ["tenant_id", "source_lead_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_commercial_contracts_tenant_parent",
        "commercial_contracts",
        "commercial_contracts",
        ["tenant_id", "parent_contract_id"],
        ["tenant_id", "id"],
    )

    for column in (
        sa.Column("sent_artifact_object_key", sa.String(500)),
        sa.Column("sent_artifact_sha256", sa.String(64)),
        sa.Column("sent_artifact_file_name", sa.String(255)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("gmail_message_id", sa.String(100)),
        sa.Column("gmail_thread_id", sa.String(100)),
        sa.Column("reply_detected_at", sa.DateTime(timezone=True)),
        sa.Column("reply_message_id", sa.String(100)),
        sa.Column("signed_artifact_file_name", sa.String(255)),
        sa.Column("signature_precheck_status", sa.String(30)),
        sa.Column("signature_precheck_details", sa.JSON()),
        sa.Column("firmaec_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("firmaec_confirmed_by", sa.String(200)),
    ):
        op.add_column("commercial_contract_versions", column)

    op.add_column(
        "commercial_billing_proposals",
        sa.Column("sales_document_id", postgresql.UUID(), nullable=True),
    )
    op.add_column("commercial_billing_proposals", sa.Column("period_start", sa.Date()))
    op.add_column("commercial_billing_proposals", sa.Column("period_end", sa.Date()))
    op.add_column(
        "commercial_billing_proposals",
        sa.Column("pricing_rule_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "commercial_billing_proposals",
        sa.Column("billing_type", sa.String(30), nullable=False, server_default="ONE_OFF"),
    )
    op.add_column(
        "commercial_billing_proposals",
        sa.Column("report_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "commercial_billing_proposals",
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("commercial_billing_proposals", sa.Column("report_object_key", sa.String(500)))
    op.add_column("commercial_billing_proposals", sa.Column("report_sha256", sa.String(64)))
    op.add_column("commercial_billing_proposals", sa.Column("report_file_name", sa.String(255)))
    op.add_column(
        "commercial_billing_proposals", sa.Column("report_approved_at", sa.DateTime(timezone=True))
    )
    op.add_column("commercial_billing_proposals", sa.Column("report_approved_by", sa.String(200)))
    op.create_foreign_key(
        "fk_billing_proposals_tenant_sales_document",
        "commercial_billing_proposals",
        "sales_documents",
        ["tenant_id", "sales_document_id"],
        ["tenant_id", "id"],
    )
    op.create_unique_constraint(
        "uq_billing_proposals_tenant_sales_document",
        "commercial_billing_proposals",
        ["tenant_id", "sales_document_id"],
    )

    op.add_column("sales_documents", sa.Column("commercial_snapshot", sa.JSON()))
    op.add_column(
        "sales_documents",
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "receivables",
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("receivables", "collection_enabled")
    op.drop_column("sales_documents", "collection_enabled")
    op.drop_column("sales_documents", "commercial_snapshot")
    op.drop_constraint(
        "uq_billing_proposals_tenant_sales_document",
        "commercial_billing_proposals",
        type_="unique",
    )
    op.drop_constraint(
        "fk_billing_proposals_tenant_sales_document",
        "commercial_billing_proposals",
        type_="foreignkey",
    )
    for name in (
        "report_approved_by",
        "report_approved_at",
        "report_file_name",
        "report_sha256",
        "report_object_key",
        "collection_enabled",
        "report_required",
        "billing_type",
        "pricing_rule_index",
        "period_end",
        "period_start",
        "sales_document_id",
    ):
        op.drop_column("commercial_billing_proposals", name)
    for name in (
        "firmaec_confirmed_by",
        "firmaec_confirmed_at",
        "signature_precheck_details",
        "signature_precheck_status",
        "signed_artifact_file_name",
        "reply_message_id",
        "reply_detected_at",
        "gmail_thread_id",
        "gmail_message_id",
        "sent_at",
        "sent_artifact_file_name",
        "sent_artifact_sha256",
        "sent_artifact_object_key",
    ):
        op.drop_column("commercial_contract_versions", name)
    op.drop_constraint(
        "fk_commercial_contracts_tenant_parent", "commercial_contracts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_commercial_contracts_tenant_lead", "commercial_contracts", type_="foreignkey"
    )
    for name in (
        "collection_enabled",
        "report_required",
        "service_type",
        "parent_contract_id",
        "source_lead_id",
    ):
        op.drop_column("commercial_contracts", name)

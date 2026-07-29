"""add legal-commercial dossier core

Revision ID: f1e2d3c4b5a6
Revises: e8f9a0b1c2d3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1e2d3c4b5a6"  # pragma: allowlist secret
down_revision: str | None = "e8f9a0b1c2d3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "commercial_contracts",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("contract_number", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_commercial_contracts_tenant_party",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_commercial_contracts_tenant_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_commercial_contracts_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "contract_number", name="uq_commercial_contracts_tenant_number"
        ),
    )
    op.create_index(
        "ix_commercial_contracts_tenant_party", "commercial_contracts", ["tenant_id", "party_id"]
    )
    op.create_index("ix_commercial_contracts_tenant_id", "commercial_contracts", ["tenant_id"])
    op.create_table(
        "commercial_contract_versions",
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("renewal_notice_days", sa.Integer(), nullable=True),
        sa.Column("pricing_rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("signed_artifact_object_key", sa.String(500), nullable=True),
        sa.Column("signed_artifact_sha256", sa.String(64), nullable=True),
        sa.Column("amends_version_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "payment_terms_days >= 0", name="ck_contract_versions_payment_terms_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["commercial_contracts.tenant_id", "commercial_contracts.id"],
            name="fk_contract_versions_tenant_contract",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "amends_version_id"],
            ["commercial_contract_versions.tenant_id", "commercial_contract_versions.id"],
            name="fk_contract_versions_tenant_amendment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_contract_versions_tenant_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contract_versions_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "contract_id",
            "version_number",
            name="uq_contract_versions_tenant_contract_number",
        ),
    )
    op.create_index(
        "ix_contract_versions_tenant_contract",
        "commercial_contract_versions",
        ["tenant_id", "contract_id"],
    )
    op.create_index(
        "ix_commercial_contract_versions_tenant_id", "commercial_contract_versions", ["tenant_id"]
    )
    op.create_table(
        "aws_consumption_cuts",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="IMPORTED"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("total_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("evidence_object_key", sa.String(500), nullable=True),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("reconciliation_summary", sa.JSON(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("total_cost >= 0", name="ck_aws_cuts_total_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_aws_cuts_tenant_party",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_aws_cuts_tenant_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_aws_cuts_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "party_id",
            "period_start",
            "period_end",
            name="uq_aws_cuts_tenant_party_period",
        ),
    )
    op.create_index("ix_aws_cuts_tenant_party", "aws_consumption_cuts", ["tenant_id", "party_id"])
    op.create_index("ix_aws_consumption_cuts_tenant_id", "aws_consumption_cuts", ["tenant_id"])
    op.create_table(
        "commercial_billing_proposals",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("contract_version_id", sa.Uuid(), nullable=True),
        sa.Column("aws_consumption_cut_id", sa.Uuid(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("commercial_snapshot", sa.JSON(), nullable=False),
        sa.Column("exception_reason", sa.Text(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("total_amount >= 0", name="ck_billing_proposals_total_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_billing_proposals_tenant_party",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_version_id"],
            ["commercial_contract_versions.tenant_id", "commercial_contract_versions.id"],
            name="fk_billing_proposals_tenant_contract_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "aws_consumption_cut_id"],
            ["aws_consumption_cuts.tenant_id", "aws_consumption_cuts.id"],
            name="fk_billing_proposals_tenant_cut",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_billing_proposals_tenant_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_proposals_tenant_party",
        "commercial_billing_proposals",
        ["tenant_id", "party_id"],
    )
    op.create_index(
        "ix_commercial_billing_proposals_tenant_id",
        "commercial_billing_proposals",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_commercial_billing_proposals_tenant_id", table_name="commercial_billing_proposals"
    )
    op.drop_index("ix_billing_proposals_tenant_party", table_name="commercial_billing_proposals")
    op.drop_table("commercial_billing_proposals")
    op.drop_index("ix_aws_consumption_cuts_tenant_id", table_name="aws_consumption_cuts")
    op.drop_index("ix_aws_cuts_tenant_party", table_name="aws_consumption_cuts")
    op.drop_table("aws_consumption_cuts")
    op.drop_index(
        "ix_commercial_contract_versions_tenant_id", table_name="commercial_contract_versions"
    )
    op.drop_index("ix_contract_versions_tenant_contract", table_name="commercial_contract_versions")
    op.drop_table("commercial_contract_versions")
    op.drop_index("ix_commercial_contracts_tenant_id", table_name="commercial_contracts")
    op.drop_index("ix_commercial_contracts_tenant_party", table_name="commercial_contracts")
    op.drop_table("commercial_contracts")

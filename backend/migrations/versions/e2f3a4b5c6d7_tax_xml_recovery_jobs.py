"""add tax XML recovery jobs

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"  # pragma: allowlist secret
down_revision: str | None = "d1e2f3a4b5c6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tax_xml_recovery_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("recovered_count", sa.Integer(), nullable=False),
        sa.Column("unavailable_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("requested_by_actor_id", sa.String(length=200), nullable=False),
        sa.Column("requested_by_actor_type", sa.String(length=30), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED')",
            name="ck_tax_xml_recovery_jobs_tax_xml_recovery_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_xml_recovery_jobs_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tax_xml_recovery_jobs_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_xml_recovery_jobs"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_xml_recovery_jobs_tenant_id"),
    )
    op.create_index(
        "ix_tax_xml_recovery_jobs_tenant_id",
        "tax_xml_recovery_jobs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tax_xml_recovery_jobs_tenant_period_created",
        "tax_xml_recovery_jobs",
        ["tenant_id", "tax_period_id", "created_at"],
    )
    op.create_table(
        "tax_xml_recovery_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("fiscal_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RECOVERED', 'UNAVAILABLE', 'FAILED')",
            name="ck_tax_xml_recovery_items_tax_xml_recovery_item_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["tax_xml_recovery_jobs.tenant_id", "tax_xml_recovery_jobs.id"],
            name="fk_tax_xml_recovery_items_tenant_job",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_tax_xml_recovery_items_tenant_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tax_xml_recovery_items_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_xml_recovery_items"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_id",
            "fiscal_document_id",
            name="uq_tax_xml_recovery_items_job_document",
        ),
    )
    op.create_index(
        "ix_tax_xml_recovery_items_tenant_id",
        "tax_xml_recovery_items",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tax_xml_recovery_items_job_status",
        "tax_xml_recovery_items",
        ["tenant_id", "job_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tax_xml_recovery_items_job_status",
        table_name="tax_xml_recovery_items",
    )
    op.drop_index("ix_tax_xml_recovery_items_tenant_id", table_name="tax_xml_recovery_items")
    op.drop_table("tax_xml_recovery_items")
    op.drop_index(
        "ix_tax_xml_recovery_jobs_tenant_period_created",
        table_name="tax_xml_recovery_jobs",
    )
    op.drop_index("ix_tax_xml_recovery_jobs_tenant_id", table_name="tax_xml_recovery_jobs")
    op.drop_table("tax_xml_recovery_jobs")

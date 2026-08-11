"""add tenant analytic classifications

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytic_classifications",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_analytic_classifications_tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_analytic_classifications_tenant_id"),
    )
    op.create_index(
        "ix_analytic_classifications_tenant_id", "analytic_classifications", ["tenant_id"]
    )
    op.create_table(
        "analytic_classification_values",
        sa.Column("classification_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "classification_id"],
            ["analytic_classifications.tenant_id", "analytic_classifications.id"],
            name="fk_analytic_values_tenant_classification",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["analytic_classification_values.tenant_id", "analytic_classification_values.id"],
            name="fk_analytic_values_tenant_parent",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "classification_id",
            "code",
            name="uq_analytic_values_tenant_classification_code",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_analytic_values_tenant_id"),
    )
    op.create_index(
        "ix_analytic_classification_values_tenant_id",
        "analytic_classification_values",
        ["tenant_id"],
    )
    op.create_index(
        "ix_analytic_values_tenant_classification_parent",
        "analytic_classification_values",
        ["tenant_id", "classification_id", "parent_id"],
    )
    op.create_table(
        "analytic_assignments",
        sa.Column("classification_id", sa.Uuid(), nullable=False),
        sa.Column("value_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("path_snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "classification_id"],
            ["analytic_classifications.tenant_id", "analytic_classifications.id"],
            name="fk_analytic_assignments_tenant_classification",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "value_id"],
            ["analytic_classification_values.tenant_id", "analytic_classification_values.id"],
            name="fk_analytic_assignments_tenant_value",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_analytic_assignments_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_id",
            "classification_id",
            name="uq_analytic_assignments_target_classification",
        ),
    )
    op.create_index("ix_analytic_assignments_tenant_id", "analytic_assignments", ["tenant_id"])
    op.create_index(
        "ix_analytic_assignments_target",
        "analytic_assignments",
        ["tenant_id", "target_type", "target_id"],
    )
    op.create_index(
        "ix_analytic_assignments_value", "analytic_assignments", ["tenant_id", "value_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_analytic_assignments_value", table_name="analytic_assignments")
    op.drop_index("ix_analytic_assignments_target", table_name="analytic_assignments")
    op.drop_index("ix_analytic_assignments_tenant_id", table_name="analytic_assignments")
    op.drop_table("analytic_assignments")
    op.drop_index(
        "ix_analytic_values_tenant_classification_parent",
        table_name="analytic_classification_values",
    )
    op.drop_index(
        "ix_analytic_classification_values_tenant_id", table_name="analytic_classification_values"
    )
    op.drop_table("analytic_classification_values")
    op.drop_index("ix_analytic_classifications_tenant_id", table_name="analytic_classifications")
    op.drop_table("analytic_classifications")

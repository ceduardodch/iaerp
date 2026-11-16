"""Add tenant rules for fiscal classification of received invoices."""

import sqlalchemy as sa
from alembic import op

revision: str = "39f30b8c2e77"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "a123bc456def"  # pragma: allowlist secret -- Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_tax_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_ruc", sa.String(13), nullable=False),
        sa.Column("tax_classification", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "tax_classification IN ('DEDUCTIBLE_CONFIRMED', 'NON_DEDUCTIBLE')",
            name="tax_classification_valid",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "supplier_ruc", name="uq_purchase_tax_rules_supplier"),
    )
    op.create_index("ix_purchase_tax_rules_tenant_id", "purchase_tax_rules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_tax_rules_tenant_id", table_name="purchase_tax_rules")
    op.drop_table("purchase_tax_rules")

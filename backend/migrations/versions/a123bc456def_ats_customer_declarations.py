"""Remember tenant-scoped customer classification for ATS only."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a123bc456def"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "f7a8b9c0d1e2"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ats_customer_declarations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("identification", sa.String(13), nullable=False),
        sa.Column("customer_type", sa.String(2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ats_customer_declarations")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ats_customer_declarations_tenant_id_tenants"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "identification", name="uq_ats_customer_declarations_tenant_identification"
        ),
        sa.CheckConstraint(
            "customer_type IN ('01', '02')",
            name=op.f("ck_ats_customer_declarations_customer_type_valid"),
        ),
        sa.CheckConstraint(
            "length(identification) BETWEEN 3 AND 13",
            name=op.f("ck_ats_customer_declarations_identification_length_valid"),
        ),
    )
    op.create_index(
        op.f("ix_ats_customer_declarations_tenant_id"), "ats_customer_declarations", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ats_customer_declarations_tenant_id"), table_name="ats_customer_declarations"
    )
    op.drop_table("ats_customer_declarations")

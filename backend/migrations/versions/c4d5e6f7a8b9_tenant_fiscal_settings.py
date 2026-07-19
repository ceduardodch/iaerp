"""add tenant fiscal settings

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_fiscal_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sri_environment", sa.String(length=1), nullable=False, server_default="1"),
        sa.Column("certificate_object_key", sa.String(length=500), nullable=True),
        sa.Column("certificate_password_encrypted", sa.Text(), nullable=True),
        sa.Column("certificate_fingerprint_sha256", sa.String(length=64), nullable=True),
        sa.Column("certificate_subject", sa.String(length=500), nullable=True),
        sa.Column("certificate_valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "sri_environment IN ('1', '2')",
            name="ck_tenant_fiscal_settings_sri_environment_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_fiscal_settings_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_fiscal_settings"),
    )


def downgrade() -> None:
    op.drop_table("tenant_fiscal_settings")

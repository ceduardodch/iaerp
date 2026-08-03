"""Add the tenant invoice email sender alias.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "c8d9e0f1a2b3"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("invoice_email_from_address", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("invoice_email_from_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_fiscal_settings", "invoice_email_from_name")
    op.drop_column("tenant_fiscal_settings", "invoice_email_from_address")

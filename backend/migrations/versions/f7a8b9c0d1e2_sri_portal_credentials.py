"""store tenant SRI portal credentials encrypted

Revision ID: f7a8b9c0d1e2
Revises: f6a7b8c9d0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "f6a7b8c9d0e1"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("sri_portal_ruc", sa.String(length=13), nullable=True),
    )
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("sri_portal_password_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("sri_portal_credentials_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_fiscal_settings", "sri_portal_credentials_updated_at")
    op.drop_column("tenant_fiscal_settings", "sri_portal_password_encrypted")
    op.drop_column("tenant_fiscal_settings", "sri_portal_ruc")

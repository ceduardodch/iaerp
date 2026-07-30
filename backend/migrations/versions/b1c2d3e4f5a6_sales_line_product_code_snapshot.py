"""snapshot commercial product code on sales lines

Revision ID: b1c2d3e4f5a6
Revises: a2b3c4d5e6f7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"  # pragma: allowlist secret
down_revision: str | None = "a2b3c4d5e6f7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_document_lines", sa.Column("product_code", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("ride_logo_object_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "tenant_fiscal_settings", sa.Column("ride_logo_sha256", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenant_fiscal_settings", "ride_logo_sha256")
    op.drop_column("tenant_fiscal_settings", "ride_logo_object_key")
    op.drop_column("sales_document_lines", "product_code")

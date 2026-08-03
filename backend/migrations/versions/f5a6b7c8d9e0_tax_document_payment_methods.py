"""persist payment methods from authorized tax documents

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"  # pragma: allowlist secret
down_revision: str | None = "e4f5a6b7c8d9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fiscal_documents",
        sa.Column(
            "payment_methods",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("fiscal_documents", "payment_methods")

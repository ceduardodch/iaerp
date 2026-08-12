"""fix analytic timestamp defaults

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "a7b8c9d0e1f2"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "analytic_classifications",
    "analytic_classification_values",
    "analytic_assignments",
)


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.alter_column(
            table,
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            existing_nullable=False,
        )
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            existing_nullable=False,
        )

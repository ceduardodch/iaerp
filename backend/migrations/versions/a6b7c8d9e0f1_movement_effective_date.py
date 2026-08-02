"""Add the evidence-backed effective date to receivable movements.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("movements", sa.Column("effective_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("movements", "effective_date")

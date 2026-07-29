"""add expected withholding profile to party

Revision ID: a2b3c4d5e6f7
Revises: f1e2d3c4b5a6
Create Date: 2026-07-29 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"  # pragma: allowlist secret
down_revision: str | None = "f1e2d3c4b5a6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "parties", sa.Column("expected_iva_withholding_rate", sa.Numeric(5, 2), nullable=True)
    )
    op.add_column(
        "parties", sa.Column("expected_income_withholding_rate", sa.Numeric(5, 2), nullable=True)
    )
    op.add_column(
        "parties", sa.Column("withholding_profile_valid_from", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("parties", "withholding_profile_valid_from")
    op.drop_column("parties", "expected_income_withholding_rate")
    op.drop_column("parties", "expected_iva_withholding_rate")

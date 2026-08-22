"""separate payable internal and tax classifications

Revision ID: b0c1d2e3f4a5
Revises: a9b8c7d6e5f4
Create Date: 2026-08-22 10:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "a9b8c7d6e5f4"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payables",
        sa.Column(
            "internal_classification",
            sa.String(length=30),
            server_default=sa.text("'PENDING_REVIEW'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "payables_internal_classification_valid",
        "payables",
        "internal_classification IN ('PENDING_REVIEW', 'REAL', 'DECLARATION_ONLY')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "payables_internal_classification_valid",
        "payables",
        type_="check",
    )
    op.drop_column("payables", "internal_classification")

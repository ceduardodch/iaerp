"""Identificar las compras manuales de servicios digitales importados."""

import sqlalchemy as sa
from alembic import op

revision = "d219c2a57e41"  # pragma: allowlist secret -- Alembic revision ID
down_revision = "6f04a29d8b37"  # pragma: allowlist secret -- Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payables",
        sa.Column(
            "foreign_digital_service", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("payables", "foreign_digital_service")

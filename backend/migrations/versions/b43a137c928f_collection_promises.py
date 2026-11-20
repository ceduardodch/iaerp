"""Store the promised payment day and the confirmed scope of individual mail."""

import sqlalchemy as sa
from alembic import op

revision = "b43a137c928f"  # pragma: allowlist secret -- Alembic revision ID
down_revision = "a914ced2073b"  # pragma: allowlist secret -- Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receivables", sa.Column("promised_date", sa.Date(), nullable=True))
    op.add_column(
        "collection_reminders", sa.Column("native_confirmation", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("collection_reminders", "native_confirmation")
    op.drop_column("receivables", "promised_date")

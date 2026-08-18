"""track whether a payable due date is known

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "b8c9d0e1f2a3"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payables",
        sa.Column(
            "due_date_known",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.execute(
        """
        UPDATE payables AS payable
        SET due_date_known = false
        WHERE payable.fiscal_document_id IS NOT NULL
          AND payable.tax_classification = 'DEDUCTIBLE_PENDING_REVIEW'
          AND payable.due_date = payable.issue_date
          AND NOT EXISTS (
              SELECT 1
              FROM supplier_payment_schedules AS schedule
              WHERE schedule.tenant_id = payable.tenant_id
                AND schedule.payable_id = payable.id
                AND schedule.status = 'SCHEDULED'
          )
        """
    )


def downgrade() -> None:
    op.drop_column("payables", "due_date_known")

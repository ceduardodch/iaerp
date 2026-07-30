"""archive failed sales documents without deleting fiscal evidence

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"  # pragma: allowlist secret
down_revision: str | None = "b1c2d3e4f5a6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_documents",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("sales_documents", sa.Column("archived_reason", sa.String(500), nullable=True))
    op.create_index(
        "ix_sales_documents_tenant_archived_at",
        "sales_documents",
        ["tenant_id", "archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sales_documents_tenant_archived_at", table_name="sales_documents")
    op.drop_column("sales_documents", "archived_reason")
    op.drop_column("sales_documents", "archived_at")

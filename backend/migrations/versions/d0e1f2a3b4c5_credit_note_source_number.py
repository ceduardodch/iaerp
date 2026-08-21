"""persist the source document number for received credit notes

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "c9d0e1f2a3b4"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fiscal_documents",
        sa.Column("related_document_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "fiscal_documents",
        sa.Column("related_document_number", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_fiscal_documents_credit_note_source",
        "fiscal_documents",
        [
            "tenant_id",
            "direction",
            "counterparty_identification",
            "related_document_number",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fiscal_documents_credit_note_source",
        table_name="fiscal_documents",
    )
    op.drop_column("fiscal_documents", "related_document_number")
    op.drop_column("fiscal_documents", "related_document_type")

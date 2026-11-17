"""Keep an evidenced local cancellation separate from source XML and payments."""

import sqlalchemy as sa
from alembic import op

revision: str = "5d6e7f8a9b0c"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "39f30b8c2e77"  # pragma: allowlist secret -- Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fiscal_documents", sa.Column("cancellation_date", sa.Date(), nullable=True))
    op.add_column(
        "fiscal_documents", sa.Column("cancellation_reason", sa.String(500), nullable=True)
    )
    op.add_column(
        "fiscal_documents", sa.Column("cancellation_evidence_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "fiscal_documents", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "fiscal_documents", sa.Column("cancelled_by_actor_id", sa.String(200), nullable=True)
    )
    op.create_foreign_key(
        "fk_fiscal_documents_cancellation_evidence",
        "fiscal_documents",
        "tax_evidence",
        ["tenant_id", "cancellation_evidence_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(
        "cancellation_complete",
        "fiscal_documents",
        "(cancelled_at IS NULL AND cancellation_date IS NULL AND "
        "cancellation_reason IS NULL AND cancellation_evidence_id IS NULL AND "
        "cancelled_by_actor_id IS NULL) OR "
        "(cancelled_at IS NOT NULL AND cancellation_date IS NOT NULL AND "
        "cancellation_reason IS NOT NULL AND cancellation_evidence_id IS NOT NULL AND "
        "cancelled_by_actor_id IS NOT NULL AND direction = 'RECIBIDO' AND "
        "doc_type = 'FACTURA' AND cancellation_date >= issue_date)",
    )


def downgrade() -> None:
    op.drop_constraint("cancellation_complete", "fiscal_documents", type_="check")
    op.drop_constraint(
        "fk_fiscal_documents_cancellation_evidence", "fiscal_documents", type_="foreignkey"
    )
    for column in (
        "cancelled_by_actor_id",
        "cancelled_at",
        "cancellation_evidence_id",
        "cancellation_reason",
        "cancellation_date",
    ):
        op.drop_column("fiscal_documents", column)

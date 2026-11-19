"""Durable mobile invoice mail delivery receipts."""

import sqlalchemy as sa
from alembic import op

revision = "a914ced2073b"
down_revision = "5d6e7f8a9b0c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_email_dispatches",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(100), primary_key=True),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("provider_message_id", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["sales_documents.tenant_id", "sales_documents.id"]
        ),
        sa.UniqueConstraint("tenant_id", "actor_id", "idempotency_key"),
    )
    op.create_index(
        "ix_invoice_email_dispatches_invoice",
        "invoice_email_dispatches",
        ["tenant_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_table("invoice_email_dispatches")

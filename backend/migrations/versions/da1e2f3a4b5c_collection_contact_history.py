"""add collection contact history and provider delivery state

Revision ID: da1e2f3a4b5c
Revises: d9e0f1a2b3c4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "da1e2f3a4b5c"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("collection_reminders", sa.Column("provider_message_id", sa.String(200)))
    op.add_column(
        "collection_reminders",
        sa.Column("delivery_status", sa.String(20), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column("collection_reminders", sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.add_column("collection_reminders", sa.Column("read_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_collection_reminders_provider_message",
        "collection_reminders",
        ["tenant_id", "provider_message_id"],
    )
    op.create_table(
        "collection_contacts",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("receivable_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("note", sa.String(1000)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "channel IN ('CALL', 'EMAIL', 'WHATSAPP', 'NOTE')",
            name="ck_collection_contacts_channel",
        ),
        sa.CheckConstraint(
            "outcome IN ('PENDING', 'CONTACTED', 'PROMISE_TO_PAY', 'NO_RESPONSE', 'WRONG_CONTACT')",
            name="ck_collection_contacts_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_collection_contacts_tenant_party",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_collection_contacts_tenant_receivable",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_collection_contacts_tenant_id"),
    )
    op.create_index(
        "ix_collection_contacts_tenant_receivable_occurred",
        "collection_contacts",
        ["tenant_id", "receivable_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collection_contacts_tenant_receivable_occurred", table_name="collection_contacts"
    )
    op.drop_table("collection_contacts")
    op.drop_index("ix_collection_reminders_provider_message", table_name="collection_reminders")
    op.drop_column("collection_reminders", "read_at")
    op.drop_column("collection_reminders", "delivered_at")
    op.drop_column("collection_reminders", "delivery_status")
    op.drop_column("collection_reminders", "provider_message_id")

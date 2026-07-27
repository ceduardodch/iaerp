"""add Evolution WhatsApp integration and routing policy

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"  # pragma: allowlist secret
down_revision: str | None = "d7e8f9a0b1c2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_evolution_whatsapp_integrations",
        sa.Column("instance_name", sa.String(length=100), nullable=False),
        sa.Column("display_phone_number", sa.String(length=40), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("webhook_token_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_crm_evolution_whatsapp_tenant"),
    )
    op.create_index(
        "ix_crm_evolution_whatsapp_integrations_tenant_id",
        "crm_evolution_whatsapp_integrations",
        ["tenant_id"],
    )
    op.create_table(
        "crm_whatsapp_routing_policies",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("crm_provider", sa.String(length=20), nullable=False, server_default="META"),
        sa.Column(
            "collections_provider", sa.String(length=20), nullable=False, server_default="META"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("crm_provider IN ('META', 'EVOLUTION')", name="crm_provider_valid"),
        sa.CheckConstraint(
            "collections_provider IN ('META', 'EVOLUTION')", name="collections_provider_valid"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("crm_whatsapp_routing_policies")
    op.drop_index(
        "ix_crm_evolution_whatsapp_integrations_tenant_id",
        table_name="crm_evolution_whatsapp_integrations",
    )
    op.drop_table("crm_evolution_whatsapp_integrations")

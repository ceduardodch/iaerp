"""add crm models (Lead, LeadActivity, GmailIntegration)

Revision ID: a1b2c3d4e5f6
Revises: add_collection_reminder
Create Date: 2026-07-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "add_collection_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create crm_leads table
    op.create_table(
        "crm_leads",
        sa.Column("party_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="NEW"),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "hotness",
            sa.String(length=10),
            nullable=False,
            server_default="COLD"
        ),
        sa.Column("estimated_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "hotness IN ('COLD', 'WARM', 'HOT')",
            name="ck_crm_leads_hotness_valid"
        ),
        sa.CheckConstraint(
            "score >= 0",
            name="ck_crm_leads_score_non_negative"
        ),
        sa.CheckConstraint(
            "score <= 100",
            name="ck_crm_leads_score_max_100"
        ),
        sa.CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST')",
            name="ck_crm_leads_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_crm_leads_tenant_party",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_crm_leads_tenant_id",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_crm_leads_owner_user_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crm_leads"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_leads_tenant_id"),
    )
    op.create_index(
        "ix_crm_leads_tenant_status",
        "crm_leads",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_crm_leads_tenant_owner",
        "crm_leads",
        ["tenant_id", "owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_leads_tenant_id",
        "crm_leads",
        ["tenant_id"],
        unique=False,
    )

    # Create crm_activities table
    op.create_table(
        "crm_activities",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column(
            "activity_type",
            sa.String(length=20),
            nullable=False
        ),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "outcome",
            sa.String(length=20),
            nullable=False
        ),
        sa.Column(
            "reminder_date",
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column("reminder_completed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("source_email_id", sa.String(length=100), nullable=True),
        sa.Column("source_email_thread_id", sa.String(length=100), nullable=True),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "activity_type IN ('CALL', 'EMAIL', 'MEETING', 'NOTE', 'TASK')",
            name="ck_crm_activities_activity_type_valid"
        ),
        sa.CheckConstraint(
            "outcome IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE', 'PENDING')",
            name="ck_crm_activities_outcome_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_crm_activities_tenant_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_crm_activities_tenant_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crm_activities"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_activities_tenant_id"),
    )
    op.create_index(
        "ix_crm_activities_tenant_lead",
        "crm_activities",
        ["tenant_id", "lead_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_activities_tenant_date",
        "crm_activities",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_crm_activities_tenant_id",
        "crm_activities",
        ["tenant_id"],
        unique=False,
    )

    # Create crm_gmail_integrations table
    op.create_table(
        "crm_gmail_integrations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False
        ),
        sa.Column("scopes_granted", sa.JSON(), nullable=False),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "last_sync_at",
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column("sync_labels", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_crm_gmail_integrations_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_crm_gmail_integrations_tenant_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crm_gmail_integrations"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_crm_gmail_tenant_user"),
    )
    op.create_index(
        "ix_crm_gmail_integrations_tenant_id",
        "crm_gmail_integrations",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_gmail_integrations_user_id",
        "crm_gmail_integrations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop crm_gmail_integrations table
    op.drop_index("ix_crm_gmail_integrations_user_id", table_name="crm_gmail_integrations")
    op.drop_index("ix_crm_gmail_integrations_tenant_id", table_name="crm_gmail_integrations")
    op.drop_table("crm_gmail_integrations")

    # Drop crm_activities table
    op.drop_index("ix_crm_activities_tenant_id", table_name="crm_activities")
    op.drop_index("ix_crm_activities_tenant_date", table_name="crm_activities")
    op.drop_index("ix_crm_activities_tenant_lead", table_name="crm_activities")
    op.drop_table("crm_activities")

    # Drop crm_leads table
    op.drop_index("ix_crm_leads_tenant_id", table_name="crm_leads")
    op.drop_index("ix_crm_leads_tenant_owner", table_name="crm_leads")
    op.drop_index("ix_crm_leads_tenant_status", table_name="crm_leads")
    op.drop_table("crm_leads")

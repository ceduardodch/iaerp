"""add campaign attribution to CRM leads

Revision ID: e5f6a7b8c9d0
Revises: da1e2f3a4b5c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "e6f7a8b9c0d1"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name, length in (
        ("source_external_id", 200),
        ("campaign_id", 100),
        ("campaign_name", 200),
        ("ad_id", 100),
        ("utm_source", 100),
        ("utm_medium", 100),
        ("utm_campaign", 200),
        ("utm_content", 200),
        ("consent_text_version", 100),
    ):
        op.add_column("crm_leads", sa.Column(name, sa.String(length), nullable=True))
    op.add_column("crm_leads", sa.Column("consent_captured_at", sa.DateTime(timezone=True)))
    op.add_column(
        "crm_leads",
        sa.Column(
            "qualification_status",
            sa.String(20),
            nullable=False,
            server_default="UNREVIEWED",
        ),
    )
    op.add_column("crm_leads", sa.Column("qualified_at", sa.DateTime(timezone=True)))
    op.add_column("crm_leads", sa.Column("qualified_by", sa.String(200)))
    op.add_column("crm_leads", sa.Column("company_name", sa.String(200)))
    op.add_column("crm_leads", sa.Column("job_title", sa.String(150)))
    op.add_column("crm_leads", sa.Column("uses_aws", sa.Boolean()))
    op.add_column("crm_leads", sa.Column("decision_authority", sa.Boolean()))
    op.add_column("crm_leads", sa.Column("qualification_reason", sa.Text()))
    op.create_check_constraint(
        "qualification_status_valid",
        "crm_leads",
        "qualification_status IN ('UNREVIEWED', 'QUALIFIED', 'DISQUALIFIED')",
    )
    op.create_index(
        "ix_crm_leads_tenant_qualification",
        "crm_leads",
        ["tenant_id", "qualification_status"],
    )
    op.create_unique_constraint(
        "uq_crm_leads_tenant_source_external",
        "crm_leads",
        ["tenant_id", "source", "source_external_id"],
    )
    op.create_table(
        "crm_lead_campaign_touches",
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_external_id", sa.String(200), nullable=False),
        sa.Column("campaign_id", sa.String(100), nullable=True),
        sa.Column("campaign_name", sa.String(200), nullable=True),
        sa.Column("ad_id", sa.String(100), nullable=True),
        sa.Column("utm_source", sa.String(100), nullable=True),
        sa.Column("utm_medium", sa.String(100), nullable=True),
        sa.Column("utm_campaign", sa.String(200), nullable=True),
        sa.Column("utm_content", sa.String(200), nullable=True),
        sa.Column("consent_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_text_version", sa.String(100), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_crm_lead_campaign_touches_tenant_lead",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source",
            "source_external_id",
            name="uq_crm_lead_campaign_touch_source",
        ),
    )
    op.create_index(
        "ix_crm_lead_campaign_touches_tenant_id",
        "crm_lead_campaign_touches",
        ["tenant_id"],
    )
    op.create_index(
        "ix_crm_lead_campaign_touches_tenant_lead",
        "crm_lead_campaign_touches",
        ["tenant_id", "lead_id"],
    )
    op.create_table(
        "crm_meta_ads_integrations",
        sa.Column("ad_account_id", sa.String(100), nullable=False),
        sa.Column("page_id", sa.String(100), nullable=False),
        sa.Column("instagram_actor_id", sa.String(100), nullable=True),
        sa.Column("default_lead_form_id", sa.String(100), nullable=False),
        sa.Column("account_currency", sa.String(3), nullable=True),
        sa.Column("account_timezone", sa.String(100), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("app_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("verify_token_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", name="uq_crm_meta_ads_page"),
        sa.UniqueConstraint("tenant_id", name="uq_crm_meta_ads_tenant"),
    )
    op.create_index(
        "ix_crm_meta_ads_integrations_tenant_id",
        "crm_meta_ads_integrations",
        ["tenant_id"],
    )
    op.create_table(
        "crm_social_campaign_policies",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("activation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "daily_budget_limit",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "daily_budget_limit >= 0",
            name="ck_crm_social_campaign_policy_budget",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "crm_meta_webhook_attempts",
        sa.Column("page_id", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_meta_webhook_attempts_tenant_id",
        "crm_meta_webhook_attempts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_crm_meta_webhook_attempts_tenant_created",
        "crm_meta_webhook_attempts",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "crm_social_campaigns",
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("daily_budget", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("age_min", sa.Integer(), nullable=False),
        sa.Column("age_max", sa.Integer(), nullable=False),
        sa.Column("countries", sa.JSON(), nullable=False),
        sa.Column("primary_text", sa.Text(), nullable=False),
        sa.Column("headline", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("lead_form_id", sa.String(100), nullable=True),
        sa.Column("creative_object_key", sa.String(500), nullable=True),
        sa.Column("creative_content_type", sa.String(100), nullable=True),
        sa.Column("creative_sha256", sa.String(64), nullable=True),
        sa.Column("external_campaign_id", sa.String(100), nullable=True),
        sa.Column("external_adset_id", sa.String(100), nullable=True),
        sa.Column("external_creative_id", sa.String(100), nullable=True),
        sa.Column("external_ad_id", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PREPARING', 'PREPARED', 'ACTIVATING', "
            "'ACTIVE', 'PAUSING', 'PAUSED', 'ERROR')",
            name="ck_crm_social_campaigns_status",
        ),
        sa.CheckConstraint("provider = 'META'", name="ck_crm_social_campaigns_provider"),
        sa.CheckConstraint("daily_budget > 0", name="ck_crm_social_campaigns_budget"),
        sa.CheckConstraint(
            "age_min >= 18 AND age_max <= 65 AND age_max >= age_min",
            name="ck_crm_social_campaigns_age_range",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_social_campaigns_tenant_id"),
    )
    op.create_index("ix_crm_social_campaigns_tenant_id", "crm_social_campaigns", ["tenant_id"])
    op.create_index(
        "ix_crm_social_campaigns_tenant_status",
        "crm_social_campaigns",
        ["tenant_id", "status"],
    )
    op.create_table(
        "crm_social_campaign_variants",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("angle", sa.String(100), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("primary_text", sa.Text(), nullable=False),
        sa.Column("headline", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("creative_object_key", sa.String(500), nullable=True),
        sa.Column("creative_content_type", sa.String(100), nullable=True),
        sa.Column("creative_sha256", sa.String(64), nullable=True),
        sa.Column("external_creative_id", sa.String(100), nullable=True),
        sa.Column("external_ad_id", sa.String(100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["crm_social_campaigns.tenant_id", "crm_social_campaigns.id"],
            name="fk_crm_social_campaign_variants_tenant_campaign",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "campaign_id", "key", name="uq_crm_social_campaign_variant_key"
        ),
        sa.UniqueConstraint(
            "tenant_id", "external_ad_id", name="uq_crm_social_campaign_variant_ad"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_crm_social_campaign_variants_tenant_id"),
    )
    op.create_index(
        "ix_crm_social_campaign_variants_tenant_id",
        "crm_social_campaign_variants",
        ["tenant_id"],
    )
    op.create_index(
        "ix_crm_social_campaign_variants_tenant_campaign",
        "crm_social_campaign_variants",
        ["tenant_id", "campaign_id"],
    )
    op.create_table(
        "crm_social_campaign_metrics_daily",
        sa.Column("variant_id", sa.Uuid(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("external_ad_id", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("spend", sa.Numeric(18, 4), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("leads", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("spend >= 0", name="ck_crm_social_metrics_spend"),
        sa.CheckConstraint(
            "impressions >= 0 AND clicks >= 0 AND leads >= 0",
            name="ck_crm_social_metrics_counts",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["crm_social_campaign_variants.tenant_id", "crm_social_campaign_variants.id"],
            name="fk_crm_social_campaign_metrics_tenant_variant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "variant_id", "metric_date", name="uq_crm_social_metric_variant_date"
        ),
    )
    op.create_index(
        "ix_crm_social_campaign_metrics_daily_tenant_id",
        "crm_social_campaign_metrics_daily",
        ["tenant_id"],
    )
    op.create_index(
        "ix_crm_social_metrics_tenant_date",
        "crm_social_campaign_metrics_daily",
        ["tenant_id", "metric_date"],
    )
    op.add_column("crm_leads", sa.Column("campaign_variant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_crm_leads_tenant_campaign_variant",
        "crm_leads",
        "crm_social_campaign_variants",
        ["tenant_id", "campaign_variant_id"],
        ["tenant_id", "id"],
    )
    op.create_index(
        "ix_crm_leads_tenant_campaign_variant",
        "crm_leads",
        ["tenant_id", "campaign_variant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_leads_tenant_campaign_variant", table_name="crm_leads")
    op.drop_constraint("fk_crm_leads_tenant_campaign_variant", "crm_leads", type_="foreignkey")
    op.drop_column("crm_leads", "campaign_variant_id")
    op.drop_index(
        "ix_crm_social_metrics_tenant_date",
        table_name="crm_social_campaign_metrics_daily",
    )
    op.drop_index(
        "ix_crm_social_campaign_metrics_daily_tenant_id",
        table_name="crm_social_campaign_metrics_daily",
    )
    op.drop_table("crm_social_campaign_metrics_daily")
    op.drop_index(
        "ix_crm_social_campaign_variants_tenant_campaign",
        table_name="crm_social_campaign_variants",
    )
    op.drop_index(
        "ix_crm_social_campaign_variants_tenant_id",
        table_name="crm_social_campaign_variants",
    )
    op.drop_table("crm_social_campaign_variants")
    op.drop_index("ix_crm_social_campaigns_tenant_status", table_name="crm_social_campaigns")
    op.drop_index("ix_crm_social_campaigns_tenant_id", table_name="crm_social_campaigns")
    op.drop_table("crm_social_campaigns")
    op.drop_index(
        "ix_crm_meta_webhook_attempts_tenant_created",
        table_name="crm_meta_webhook_attempts",
    )
    op.drop_index(
        "ix_crm_meta_webhook_attempts_tenant_id",
        table_name="crm_meta_webhook_attempts",
    )
    op.drop_table("crm_meta_webhook_attempts")
    op.drop_table("crm_social_campaign_policies")
    op.drop_index("ix_crm_meta_ads_integrations_tenant_id", table_name="crm_meta_ads_integrations")
    op.drop_table("crm_meta_ads_integrations")
    op.drop_index(
        "ix_crm_lead_campaign_touches_tenant_lead",
        table_name="crm_lead_campaign_touches",
    )
    op.drop_index(
        "ix_crm_lead_campaign_touches_tenant_id",
        table_name="crm_lead_campaign_touches",
    )
    op.drop_table("crm_lead_campaign_touches")
    op.drop_constraint("uq_crm_leads_tenant_source_external", "crm_leads", type_="unique")
    op.drop_index("ix_crm_leads_tenant_qualification", table_name="crm_leads")
    op.drop_constraint("qualification_status_valid", "crm_leads", type_="check")
    for name in (
        "qualification_reason",
        "decision_authority",
        "uses_aws",
        "job_title",
        "company_name",
        "qualified_by",
        "qualified_at",
        "qualification_status",
    ):
        op.drop_column("crm_leads", name)
    op.drop_column("crm_leads", "consent_captured_at")
    for name in (
        "consent_text_version",
        "utm_content",
        "utm_campaign",
        "utm_medium",
        "utm_source",
        "ad_id",
        "campaign_name",
        "campaign_id",
        "source_external_id",
    ):
        op.drop_column("crm_leads", name)

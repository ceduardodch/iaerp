import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import Party, Product, TenantEntityMixin
from app.models.platform import User


class LeadStatus(StrEnum):
    """Estados del pipeline de ventas."""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Prospecto principal del CRM."""

    __tablename__ = "crm_leads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_crm_leads_tenant_party",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_crm_leads_tenant_product",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_variant_id"],
            ["crm_social_campaign_variants.tenant_id", "crm_social_campaign_variants.id"],
            name="fk_crm_leads_tenant_campaign_variant",
        ),
        CheckConstraint("hotness IN ('COLD', 'WARM', 'HOT')", name="hotness_valid"),
        CheckConstraint("score >= 0", name="score_non_negative"),
        CheckConstraint("score <= 100", name="score_max_100"),
        CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST')",
            name="status_valid",
        ),
        CheckConstraint(
            "qualification_status IN ('UNREVIEWED', 'QUALIFIED', 'DISQUALIFIED')",
            name="qualification_status_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crm_leads_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "source",
            "source_external_id",
            name="uq_crm_leads_tenant_source_external",
        ),
        Index("ix_crm_leads_tenant_status", "tenant_id", "status"),
        Index("ix_crm_leads_tenant_owner", "tenant_id", "owner_user_id"),
        Index(
            "ix_crm_leads_tenant_qualification",
            "tenant_id",
            "qualification_status",
        ),
        Index(
            "ix_crm_leads_tenant_campaign_variant",
            "tenant_id",
            "campaign_variant_id",
        ),
    )

    party_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[uuid.UUID | None]
    status: Mapped[LeadStatus] = mapped_column(String(20), default=LeadStatus.NEW)
    source: Mapped[str | None] = mapped_column(String(50))
    source_external_id: Mapped[str | None] = mapped_column(String(200))
    campaign_id: Mapped[str | None] = mapped_column(String(100))
    campaign_name: Mapped[str | None] = mapped_column(String(200))
    ad_id: Mapped[str | None] = mapped_column(String(100))
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(200))
    utm_content: Mapped[str | None] = mapped_column(String(200))
    consent_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_text_version: Mapped[str | None] = mapped_column(String(100))
    campaign_variant_id: Mapped[uuid.UUID | None]
    qualification_status: Mapped[str] = mapped_column(String(20), default="UNREVIEWED")
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    qualified_by: Mapped[str | None] = mapped_column(String(200))
    company_name: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(150))
    uses_aws: Mapped[bool | None]
    decision_authority: Mapped[bool | None]
    qualification_reason: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(default=0)
    hotness: Mapped[Literal["COLD", "WARM", "HOT"]] = mapped_column(String(10), default="COLD")
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expected_close_date: Mapped[date | None]

    # Relaciones
    party: Mapped[Party] = relationship(lazy="joined")
    product: Mapped["Product | None"] = relationship(lazy="joined", overlaps="party")
    owner: Mapped[User | None] = relationship(lazy="joined")
    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    campaign_touches: Mapped[list["LeadCampaignTouch"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    campaign_variant: Mapped["SocialCampaignVariant | None"] = relationship(
        lazy="joined", overlaps="party,product"
    )


class LeadCampaignTouch(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cada respuesta de campaña, incluso si reutiliza un lead existente."""

    __tablename__ = "crm_lead_campaign_touches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_crm_lead_campaign_touches_tenant_lead",
        ),
        UniqueConstraint(
            "tenant_id",
            "source",
            "source_external_id",
            name="uq_crm_lead_campaign_touch_source",
        ),
        Index(
            "ix_crm_lead_campaign_touches_tenant_lead",
            "tenant_id",
            "lead_id",
        ),
    )

    lead_id: Mapped[uuid.UUID]
    source: Mapped[str] = mapped_column(String(50))
    source_external_id: Mapped[str] = mapped_column(String(200))
    campaign_id: Mapped[str | None] = mapped_column(String(100))
    campaign_name: Mapped[str | None] = mapped_column(String(200))
    ad_id: Mapped[str | None] = mapped_column(String(100))
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(200))
    utm_content: Mapped[str | None] = mapped_column(String(200))
    consent_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_text_version: Mapped[str] = mapped_column(String(100))

    lead: Mapped[Lead] = relationship(back_populates="campaign_touches")


class LeadActivity(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Actividades y seguimientos realizados sobre un lead."""

    __tablename__ = "crm_activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_crm_activities_tenant_lead",
        ),
        CheckConstraint(
            "activity_type IN ('CALL', 'EMAIL', 'WHATSAPP', 'MEETING', 'NOTE', 'TASK')",
            name="activity_type_valid",
        ),
        CheckConstraint(
            "outcome IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE', 'PENDING')",
            name="outcome_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crm_activities_tenant_id"),
        Index("ix_crm_activities_tenant_lead", "tenant_id", "lead_id"),
        Index("ix_crm_activities_tenant_date", "tenant_id", "created_at"),
    )

    lead_id: Mapped[uuid.UUID]
    activity_type: Mapped[Literal["CALL", "EMAIL", "WHATSAPP", "MEETING", "NOTE", "TASK"]] = (
        mapped_column(String(20))
    )
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "PENDING"]] = mapped_column(
        String(20)
    )
    reminder_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_completed: Mapped[bool] = mapped_column(default=False)

    # Integración Gmail
    source_email_id: Mapped[str | None] = mapped_column(String(100))
    source_email_thread_id: Mapped[str | None] = mapped_column(String(100))

    actor_id: Mapped[str] = mapped_column(String(200))

    # Relaciones
    lead: Mapped["Lead"] = relationship(back_populates="activities")


class GmailIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Configuración de integración Gmail por tenant y usuario."""

    __tablename__ = "crm_gmail_integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_crm_gmail_tenant_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes_granted: Mapped[list[str]] = mapped_column(JSON)
    sync_enabled: Mapped[bool] = mapped_column(default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_labels: Mapped[list[str] | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)


class WhatsAppIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "crm_whatsapp_integrations"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_crm_whatsapp_tenant"),)

    business_account_id: Mapped[str] = mapped_column(String(100))
    phone_number_id: Mapped[str] = mapped_column(String(100))
    display_phone_number: Mapped[str | None] = mapped_column(String(40))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    app_secret_encrypted: Mapped[str] = mapped_column(Text)
    verify_token_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)


class EvolutionWhatsAppIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Conexión Evolution API aislada por tenant.

    La URL del servidor es una configuración de plataforma, no un dato editable
    por tenant, para no convertir esta integración en un vector SSRF.
    """

    __tablename__ = "crm_evolution_whatsapp_integrations"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_crm_evolution_whatsapp_tenant"),)

    instance_name: Mapped[str] = mapped_column(String(100))
    display_phone_number: Mapped[str | None] = mapped_column(String(40))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    webhook_token_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)


class WhatsAppRoutingPolicy(TimestampMixin, Base):
    """Proveedor de WhatsApp elegido por uso operativo del tenant."""

    __tablename__ = "crm_whatsapp_routing_policies"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    crm_provider: Mapped[str] = mapped_column(String(20), default="META")
    collections_provider: Mapped[str] = mapped_column(String(20), default="META")


class MetaAdsIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cuenta de Meta Ads usada para Facebook e Instagram por tenant."""

    __tablename__ = "crm_meta_ads_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_crm_meta_ads_tenant"),
        UniqueConstraint("page_id", name="uq_crm_meta_ads_page"),
    )

    ad_account_id: Mapped[str] = mapped_column(String(100))
    page_id: Mapped[str] = mapped_column(String(100))
    instagram_actor_id: Mapped[str | None] = mapped_column(String(100))
    default_lead_form_id: Mapped[str] = mapped_column(String(100))
    account_currency: Mapped[str | None] = mapped_column(String(3))
    account_timezone: Mapped[str | None] = mapped_column(String(100))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    app_secret_encrypted: Mapped[str] = mapped_column(Text)
    verify_token_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)


class SocialCampaignPolicy(TimestampMixin, Base):
    """Interruptor y tope de gasto diario configurados por tenant."""

    __tablename__ = "crm_social_campaign_policies"
    __table_args__ = (
        CheckConstraint(
            "daily_budget_limit >= 0",
            name="ck_crm_social_campaign_policy_budget",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"),
        primary_key=True,
    )
    activation_enabled: Mapped[bool] = mapped_column(default=False)
    daily_budget_limit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
    )


class MetaWebhookAttempt(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Intento firmado usado para limitar el webhook aun cuando el lote falle."""

    __tablename__ = "crm_meta_webhook_attempts"
    __table_args__ = (
        Index(
            "ix_crm_meta_webhook_attempts_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    page_id: Mapped[str] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64))


class SocialCampaign(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Campaña social preparada y controlada desde IAERP."""

    __tablename__ = "crm_social_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'PREPARING', 'PREPARED', 'ACTIVATING', "
            "'ACTIVE', 'PAUSING', 'PAUSED', 'ERROR')",
            name="ck_crm_social_campaigns_status",
        ),
        CheckConstraint("provider = 'META'", name="ck_crm_social_campaigns_provider"),
        CheckConstraint("daily_budget > 0", name="ck_crm_social_campaigns_budget"),
        CheckConstraint(
            "age_min >= 18 AND age_max <= 65 AND age_max >= age_min",
            name="ck_crm_social_campaigns_age_range",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crm_social_campaigns_tenant_id"),
        Index("ix_crm_social_campaigns_tenant_status", "tenant_id", "status"),
    )

    provider: Mapped[str] = mapped_column(String(20), default="META")
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    age_min: Mapped[int] = mapped_column(default=25)
    age_max: Mapped[int] = mapped_column(default=65)
    countries: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["EC"])
    primary_text: Mapped[str] = mapped_column(Text)
    headline: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    lead_form_id: Mapped[str | None] = mapped_column(String(100))
    creative_object_key: Mapped[str | None] = mapped_column(String(500))
    creative_content_type: Mapped[str | None] = mapped_column(String(100))
    creative_sha256: Mapped[str | None] = mapped_column(String(64))
    external_campaign_id: Mapped[str | None] = mapped_column(String(100))
    external_adset_id: Mapped[str | None] = mapped_column(String(100))
    external_creative_id: Mapped[str | None] = mapped_column(String(100))
    external_ad_id: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    variants: Mapped[list["SocialCampaignVariant"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SocialCampaignVariant.position",
    )


class SocialCampaignVariant(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Una variante creativa dentro del mismo conjunto de anuncios."""

    __tablename__ = "crm_social_campaign_variants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["crm_social_campaigns.tenant_id", "crm_social_campaigns.id"],
            name="fk_crm_social_campaign_variants_tenant_campaign",
        ),
        UniqueConstraint(
            "tenant_id", "campaign_id", "key", name="uq_crm_social_campaign_variant_key"
        ),
        UniqueConstraint("tenant_id", "external_ad_id", name="uq_crm_social_campaign_variant_ad"),
        UniqueConstraint("tenant_id", "id", name="uq_crm_social_campaign_variants_tenant_id"),
        Index(
            "ix_crm_social_campaign_variants_tenant_campaign",
            "tenant_id",
            "campaign_id",
        ),
    )

    campaign_id: Mapped[uuid.UUID]
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    angle: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(default=0)
    primary_text: Mapped[str] = mapped_column(Text)
    headline: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    creative_object_key: Mapped[str | None] = mapped_column(String(500))
    creative_content_type: Mapped[str | None] = mapped_column(String(100))
    creative_sha256: Mapped[str | None] = mapped_column(String(64))
    external_creative_id: Mapped[str | None] = mapped_column(String(100))
    external_ad_id: Mapped[str | None] = mapped_column(String(100))

    campaign: Mapped[SocialCampaign] = relationship(back_populates="variants")
    metrics: Mapped[list["SocialCampaignMetricDaily"]] = relationship(
        back_populates="variant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class SocialCampaignMetricDaily(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Corte diario de Meta Insights por anuncio/variante."""

    __tablename__ = "crm_social_campaign_metrics_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "variant_id"],
            ["crm_social_campaign_variants.tenant_id", "crm_social_campaign_variants.id"],
            name="fk_crm_social_campaign_metrics_tenant_variant",
        ),
        UniqueConstraint(
            "tenant_id", "variant_id", "metric_date", name="uq_crm_social_metric_variant_date"
        ),
        Index(
            "ix_crm_social_metrics_tenant_date",
            "tenant_id",
            "metric_date",
        ),
        CheckConstraint("spend >= 0", name="ck_crm_social_metrics_spend"),
        CheckConstraint(
            "impressions >= 0 AND clicks >= 0 AND leads >= 0",
            name="ck_crm_social_metrics_counts",
        ),
    )

    variant_id: Mapped[uuid.UUID]
    metric_date: Mapped[date]
    external_ad_id: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    impressions: Mapped[int]
    clicks: Mapped[int]
    leads: Mapped[int]

    variant: Mapped[SocialCampaignVariant] = relationship(back_populates="metrics")

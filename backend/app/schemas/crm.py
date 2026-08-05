import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import APIModel

# Lead Schemas
LeadStatusValue = Literal[
    "NEW",
    "CONTACTED",
    "QUALIFIED",
    "PROPOSAL",
    "NEGOTIATION",
    "WON",
    "LOST",
]


class LeadStatus(APIModel):
    """Estados válidos del pipeline de ventas."""

    NEW: Literal["NEW"] = "NEW"
    CONTACTED: Literal["CONTACTED"] = "CONTACTED"
    QUALIFIED: Literal["QUALIFIED"] = "QUALIFIED"
    PROPOSAL: Literal["PROPOSAL"] = "PROPOSAL"
    NEGOTIATION: Literal["NEGOTIATION"] = "NEGOTIATION"
    WON: Literal["WON"] = "WON"
    LOST: Literal["LOST"] = "LOST"


class LeadCreate(APIModel):
    party_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    product_id: uuid.UUID | None = None
    status: LeadStatusValue = Field(default="NEW")
    source: str | None = Field(default=None, max_length=50)
    owner_user_id: uuid.UUID | None = None
    score: int = Field(default=0, ge=0, le=100)
    hotness: Literal["COLD", "WARM", "HOT"] = Field(default="COLD")
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    expected_close_date: date | None = None


class LeadUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    product_id: uuid.UUID | None = None
    status: LeadStatusValue | None = None
    source: str | None = Field(default=None, max_length=50)
    owner_user_id: uuid.UUID | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    hotness: Literal["COLD", "WARM", "HOT"] | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    expected_close_date: date | None = None


class LeadPartyRead(APIModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    address: str | None


class LeadProductRead(APIModel):
    id: uuid.UUID
    name: str
    code: str | None


class LeadOwnerRead(APIModel):
    id: uuid.UUID
    display_name: str
    email: str


class LeadRead(LeadCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    tenant_id: uuid.UUID
    party: LeadPartyRead
    product: LeadProductRead | None = None
    owner: LeadOwnerRead | None = None
    source_external_id: str | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    ad_id: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    consent_captured_at: datetime | None = None
    consent_text_version: str | None = None
    campaign_variant_id: uuid.UUID | None = None
    qualification_status: Literal["UNREVIEWED", "QUALIFIED", "DISQUALIFIED"]
    qualified_at: datetime | None = None
    qualified_by: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    uses_aws: bool | None = None
    decision_authority: bool | None = None
    qualification_reason: str | None = None


class LeadCampaignCaptureCreate(APIModel):
    """Lead recibido por un conector de redes ya autorizado."""

    source: Literal[
        "META_LEAD_AD",
        "META_WHATSAPP",
        "LINKEDIN_LEAD_GEN",
        "TIKTOK_LEAD_GEN",
    ]
    source_external_id: str = Field(min_length=1, max_length=200)
    party_name: str = Field(min_length=1, max_length=200)
    party_email: str | None = Field(default=None, max_length=320)
    party_phone: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    campaign_id: str | None = Field(default=None, max_length=100)
    campaign_name: str | None = Field(default=None, max_length=200)
    ad_id: str | None = Field(default=None, max_length=100)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=200)
    utm_content: str | None = Field(default=None, max_length=200)
    consent_captured_at: datetime
    consent_text_version: str = Field(min_length=1, max_length=100)
    campaign_variant_id: uuid.UUID | None = None
    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=150)
    uses_aws: bool | None = None
    decision_authority: bool | None = None

    @model_validator(mode="after")
    def contact_is_required(self) -> "LeadCampaignCaptureCreate":
        if not self.party_email and not self.party_phone:
            raise ValueError("party_email or party_phone is required")
        return self

    @field_validator("party_email")
    @classmethod
    def validate_capture_email(cls, value: str | None) -> str | None:
        if value and "@" not in value:
            raise ValueError("party_email must be a valid email address")
        return value

    @field_validator("consent_captured_at")
    @classmethod
    def consent_timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("consent_captured_at must include a timezone")
        return value


class LeadCampaignCaptureRead(APIModel):
    lead: LeadRead
    created: bool
    duplicate_reason: Literal["SOURCE_REFERENCE", "CONTACT"] | None = None


class LeadQualificationUpdate(APIModel):
    status: Literal["QUALIFIED", "DISQUALIFIED"]
    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=150)
    uses_aws: bool | None = None
    decision_authority: bool | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def qualified_has_evidence(self) -> "LeadQualificationUpdate":
        if self.status == "QUALIFIED" and not (
            self.company_name and self.uses_aws is True and self.decision_authority is True
        ):
            raise ValueError(
                "qualified leads require company_name, uses_aws=true and decision_authority=true"
            )
        return self


# LeadActivity Schemas


class LeadActivityCreate(APIModel):
    lead_id: uuid.UUID
    activity_type: Literal["CALL", "EMAIL", "WHATSAPP", "MEETING", "NOTE", "TASK"]
    subject: str = Field(min_length=1, max_length=200)
    description: str | None = None
    outcome: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "PENDING"] = "PENDING"
    reminder_date: datetime | None = None
    reminder_completed: bool = False


class LeadActivityRead(LeadActivityCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    tenant_id: uuid.UUID
    actor_id: str
    source_email_id: str | None = None
    source_email_thread_id: str | None = None


class LeadActivityReminderUpdate(APIModel):
    """Cierra (o reabre) el seguimiento pendiente de una actividad."""

    completed: bool


# Gmail Integration Schemas


class GmailIntegrationRead(APIModel):
    id: uuid.UUID
    user_id: uuid.UUID
    sync_enabled: bool
    last_sync_at: datetime | None
    sync_labels: list[str] | None
    active: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: uuid.UUID


class GmailSyncResult(APIModel):
    """Resultado de una operación de sincronización Gmail."""

    messages_processed: int
    activities_created: int
    leads_matched: int
    errors: list[str]
    last_sync_at: datetime


# Pipeline Transition Schema


class LeadStatusUpdate(APIModel):
    """Solicitud para mover un lead a un nuevo estado del pipeline."""

    new_status: LeadStatusValue
    reason: str | None = Field(default=None, max_length=500)


# Party-embedded Lead Schema (para crear lead + party en una sola llamada)


class LeadWithPartyCreate(APIModel):
    """Crear un lead junto con su Party asociado."""

    party_name: str = Field(min_length=1, max_length=200)
    party_identification_type: Literal["RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"]
    party_identification_number: str = Field(min_length=1, max_length=30)
    party_email: str | None = Field(default=None, max_length=320)
    party_phone: str | None = Field(default=None, max_length=40)
    party_address: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    product_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None

    # Lead fields
    status: LeadStatusValue = Field(default="NEW")
    source: str | None = Field(default=None, max_length=50)
    score: int = Field(default=0, ge=0, le=100)
    hotness: Literal["COLD", "WARM", "HOT"] = Field(default="COLD")
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    expected_close_date: date | None = None

    @field_validator("party_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value and "@" not in value:
            raise ValueError("party_email must be a valid email address")
        return value


class IntegrationStatusRead(APIModel):
    google_connected: bool
    google_email: str | None = None
    google_last_sync_at: datetime | None = None
    google_configuration_available: bool
    whatsapp_connected: bool
    whatsapp_phone: str | None = None
    whatsapp_meta_connected: bool
    whatsapp_evolution_connected: bool
    whatsapp_evolution_phone: str | None = None
    evolution_configuration_available: bool
    whatsapp_crm_provider: Literal["META", "EVOLUTION"]
    whatsapp_collections_provider: Literal["META", "EVOLUTION"]


class GoogleAuthorizationRead(APIModel):
    authorization_url: str


class WhatsAppIntegrationUpdate(APIModel):
    business_account_id: str = Field(min_length=1, max_length=100)
    phone_number_id: str = Field(min_length=1, max_length=100)
    display_phone_number: str | None = Field(default=None, max_length=40)
    access_token: str = Field(min_length=10)
    app_secret: str = Field(min_length=10)
    verify_token: str = Field(min_length=16)


class EvolutionWhatsAppIntegrationUpdate(APIModel):
    instance_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    display_phone_number: str | None = Field(default=None, max_length=40)


class EvolutionWhatsAppIntegrationRead(APIModel):
    connected: bool
    display_phone_number: str | None = None
    webhook_url: str
    qr_code: str | None = None
    qr_expires_in_seconds: int | None = None


class WhatsAppRoutingUpdate(APIModel):
    crm_provider: Literal["META", "EVOLUTION"]
    collections_provider: Literal["META", "EVOLUTION"]


class LeadMessageCreate(APIModel):
    channel: Literal["EMAIL", "WHATSAPP"]
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    template_id: str | None = Field(default=None, max_length=100)
    # Un envío sin seguimiento agendado se pierde: la actividad queda en el
    # historial pero nadie vuelve. El servidor calcula la fecha para que no
    # dependa del reloj ni de la zona horaria del navegador.
    follow_up_days: int | None = Field(default=None, ge=1, le=90)


class MetaAdsIntegrationUpdate(APIModel):
    ad_account_id: str = Field(min_length=1, max_length=100)
    page_id: str = Field(min_length=1, max_length=100)
    instagram_actor_id: str | None = Field(default=None, max_length=100)
    default_lead_form_id: str = Field(min_length=1, max_length=100)
    access_token: str = Field(min_length=20)
    app_secret: str = Field(min_length=10)
    verify_token: str = Field(min_length=16)


class MetaAdsIntegrationRead(APIModel):
    connected: bool
    ad_account_id: str | None = None
    page_id: str | None = None
    instagram_actor_id: str | None = None
    default_lead_form_id: str | None = None
    account_currency: str | None = None
    account_timezone: str | None = None
    webhook_url: str


class SocialCampaignPolicyUpdate(APIModel):
    activation_enabled: bool
    daily_budget_limit: Decimal = Field(
        ge=0,
        le=10000,
        max_digits=18,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def enabled_policy_has_budget(self) -> "SocialCampaignPolicyUpdate":
        if self.activation_enabled and self.daily_budget_limit <= 0:
            raise ValueError("daily_budget_limit must be greater than zero when enabled")
        return self


class SocialCampaignPolicyRead(SocialCampaignPolicyUpdate):
    active_daily_budget: Decimal


CampaignStatusValue = Literal[
    "DRAFT",
    "PREPARING",
    "PREPARED",
    "ACTIVATING",
    "ACTIVE",
    "PAUSING",
    "PAUSED",
    "ERROR",
]


class SocialCampaignCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    daily_budget: Decimal = Field(gt=0, le=10000, max_digits=18, decimal_places=2)
    age_min: int = Field(default=25, ge=18, le=65)
    age_max: int = Field(default=65, ge=18, le=65)
    countries: list[str] = Field(default_factory=lambda: ["EC"], min_length=1, max_length=10)
    primary_text: str = Field(min_length=1, max_length=5000)
    headline: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    lead_form_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_age_range(self) -> "SocialCampaignCreate":
        if self.age_max < self.age_min:
            raise ValueError("age_max must be greater than or equal to age_min")
        return self

    @field_validator("countries")
    @classmethod
    def valid_countries(cls, value: list[str]) -> list[str]:
        normalized = [country.upper() for country in value]
        if any(len(country) != 2 or not country.isalpha() for country in normalized):
            raise ValueError("countries must contain ISO alpha-2 codes")
        if len(set(normalized)) != len(normalized):
            raise ValueError("countries cannot contain duplicates")
        return normalized


class SocialCampaignRead(SocialCampaignCreate):
    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: Literal["META"]
    status: CampaignStatusValue
    currency: str | None
    creative_sha256: str | None = None
    external_campaign_id: str | None = None
    external_adset_id: str | None = None
    external_creative_id: str | None = None
    external_ad_id: str | None = None
    approved_at: datetime | None = None
    activated_at: datetime | None = None
    paused_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class SocialCampaignVariantCreate(APIModel):
    key: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    angle: str | None = Field(default=None, max_length=100)
    primary_text: str = Field(min_length=1, max_length=5000)
    headline: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class SocialCampaignVariantRead(SocialCampaignVariantCreate):
    id: uuid.UUID
    campaign_id: uuid.UUID
    tenant_id: uuid.UUID
    position: int
    creative_sha256: str | None = None
    external_creative_id: str | None = None
    external_ad_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SocialCampaignInsightsSync(APIModel):
    days: int = Field(default=3, ge=1, le=30)


class SocialCampaignMetricDailyRead(APIModel):
    variant_id: uuid.UUID
    metric_date: date
    external_ad_id: str
    currency: str
    spend: Decimal
    impressions: int
    clicks: int
    leads: int


class SocialCampaignVariantDecisionRead(APIModel):
    variant: SocialCampaignVariantRead
    currency: str | None
    spend: Decimal
    impressions: int
    clicks: int
    leads: int
    qualified_leads: int
    ctr: Decimal | None
    cpl: Decimal | None
    cost_per_qualified_lead: Decimal | None


class SocialCampaignInsightsRead(APIModel):
    campaign_id: uuid.UUID
    synced_days: list[SocialCampaignMetricDailyRead]
    variants: list[SocialCampaignVariantDecisionRead]


class SocialCampaignActivation(APIModel):
    confirmed: Literal[True]

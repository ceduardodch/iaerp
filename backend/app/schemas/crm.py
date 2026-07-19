import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

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


class GoogleAuthorizationRead(APIModel):
    authorization_url: str


class WhatsAppIntegrationUpdate(APIModel):
    business_account_id: str = Field(min_length=1, max_length=100)
    phone_number_id: str = Field(min_length=1, max_length=100)
    display_phone_number: str | None = Field(default=None, max_length=40)
    access_token: str = Field(min_length=10)
    app_secret: str = Field(min_length=10)
    verify_token: str = Field(min_length=16)


class LeadMessageCreate(APIModel):
    channel: Literal["EMAIL", "WHATSAPP"]
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    template_id: str | None = Field(default=None, max_length=100)

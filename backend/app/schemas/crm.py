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
    status: LeadStatusValue = Field(default="NEW")
    source: str | None = Field(default=None, max_length=50)
    owner_user_id: uuid.UUID | None = None
    score: int = Field(default=0, ge=0, le=100)
    hotness: Literal["COLD", "WARM", "HOT"] = Field(default="COLD")
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    expected_close_date: date | None = None


class LeadUpdate(APIModel):
    status: LeadStatusValue | None = None
    source: str | None = Field(default=None, max_length=50)
    owner_user_id: uuid.UUID | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    hotness: Literal["COLD", "WARM", "HOT"] | None = None
    estimated_value: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    expected_close_date: date | None = None


class LeadRead(LeadCreate):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    tenant_id: uuid.UUID


# LeadActivity Schemas

class LeadActivityCreate(APIModel):
    lead_id: uuid.UUID
    activity_type: Literal["CALL", "EMAIL", "MEETING", "NOTE", "TASK"]
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

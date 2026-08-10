import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.base import APIModel
from app.schemas.crm import LeadActivityCreate, LeadWithPartyCreate


class MCPLeadWithPartyCreate(APIModel):
    """Alta autonoma minima; el pipeline siempre inicia en Nuevo."""

    model_config = ConfigDict(extra="forbid")

    party_name: str = Field(min_length=1, max_length=200)
    party_identification_type: Literal["RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"]
    party_identification_number: str = Field(min_length=1, max_length=30)
    party_email: str | None = Field(default=None, max_length=320)
    party_phone: str | None = Field(default=None, max_length=40)
    party_address: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def contact_is_required(self) -> "MCPLeadWithPartyCreate":
        if not self.party_email and not self.party_phone:
            raise ValueError("party_email or party_phone is required")
        return self

    def to_domain(self) -> LeadWithPartyCreate:
        return LeadWithPartyCreate(
            **self.model_dump(),
            status="NEW",
            source="MCP",
            score=0,
            hotness="COLD",
        )


class MCPLeadActivityCreate(APIModel):
    """Seguimiento autonomo acotado; no puede cerrar su propio recordatorio."""

    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID
    activity_type: Literal["CALL", "EMAIL", "WHATSAPP", "MEETING", "NOTE", "TASK"]
    subject: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    outcome: Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "PENDING"] = "PENDING"
    reminder_date: datetime | None = None

    @field_validator("reminder_date")
    @classmethod
    def reminder_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("reminder_date must include a timezone")
        return value

    def to_domain(self) -> LeadActivityCreate:
        return LeadActivityCreate(**self.model_dump(), reminder_completed=False)


class MCPLeadPartyRead(APIModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None


class MCPLeadRead(APIModel):
    id: uuid.UUID
    title: str
    status: str
    source: str | None
    score: int
    hotness: str
    party: MCPLeadPartyRead
    created_at: datetime


class MCPLeadActivityRead(APIModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    activity_type: str
    subject: str
    description: str | None
    outcome: str
    reminder_date: datetime | None
    reminder_completed: bool
    created_at: datetime

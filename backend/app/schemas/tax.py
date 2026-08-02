"""Schemas del modulo tributario (ver ``docs/adrs/0012-tax-module-scope.md``)."""

import uuid
from datetime import date, datetime

from pydantic import Field

from app.schemas.base import APIModel


class TaxPeriodRead(APIModel):
    id: uuid.UUID
    year: int
    month: int
    obligation_type: str
    status: str
    due_date: date | None = None
    notes: str | None = None


class TaxPeriodCreate(APIModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    obligation_type: str = Field(pattern="^(IVA|ATS|RDEP|RENTA|ADI)$")
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TaxEvidenceRead(APIModel):
    id: uuid.UUID
    tax_period_id: uuid.UUID | None = None
    filename: str
    file_type: str
    sha256: str
    size_bytes: int
    origin: str
    uploaded_at: datetime
    processing_notes: str | None = None
    # true cuando el archivo ya existia (mismo hash) y no se volvio a guardar.
    duplicate: bool = False

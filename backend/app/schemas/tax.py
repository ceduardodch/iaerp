"""Schemas del modulo tributario (ver ``docs/adrs/0012-tax-module-scope.md``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

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


class IngestResultRead(APIModel):
    created: int
    updated: int
    skipped: int
    preliminary: int
    notes: list[str]


class FiscalDocumentRead(APIModel):
    id: uuid.UUID
    direction: str
    doc_type: str
    access_key: str | None = None
    issue_date: date
    counterparty_identification: str | None = None
    counterparty_name: str | None = None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    is_preliminary: bool


class TaxFormFieldRead(APIModel):
    field_code: str
    label: str
    source_key: str
    # true = el usuario copia el valor al formulario; false = el SRI lo autocalcula.
    is_paste: bool
    # Formateado como `1234.56`, listo para copiar.
    value: str
    # Documentos que respaldan la cifra.
    document_count: int
    # true si este codigo aun debe confirmarse contra el formulario vigente.
    needs_review: bool = False


class IvaSummaryRead(APIModel):
    period_id: uuid.UUID
    year: int
    month: int
    status: str
    document_count: int
    is_preliminary: bool
    preliminary_reasons: list[str]
    # Todas las cifras del motor, formateadas.
    amounts: dict[str, str]
    # Campos del formulario listos para copiar/controlar.
    fields: list[TaxFormFieldRead]


class TaxAnnexRead(APIModel):
    id: uuid.UUID
    tax_period_id: uuid.UUID
    annex_type: str
    status: str
    version: int
    xml_sha256: str | None = None
    download_url: str | None = None


class SRIValidationIssueCreate(APIModel):
    severity: str = Field(default="ERROR", pattern="^(ERROR|ADVERTENCIA)$")
    line_number: int | None = Field(default=None, ge=1)
    column_number: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=4000)
    suggested_fix: str | None = Field(default=None, max_length=4000)


class SRIValidationIssueRead(SRIValidationIssueCreate):
    id: uuid.UUID
    tax_annex_id: uuid.UUID | None = None
    status: str

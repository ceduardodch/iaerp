"""Schemas del modulo tributario (ver ``docs/adrs/0012-tax-module-scope.md``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.base import APIModel
from app.schemas.masters import AnalyticAssignmentRead


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


class TaxPeriodStatusUpdate(APIModel):
    target_status: str = Field(pattern="^(LISTO_DECLARAR|DECLARADO)$")
    confirmed: bool


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


class DossierRetentionRead(APIModel):
    access_key: str | None = None
    issue_date: date
    issuer_name: str | None = None
    iva_amount: Decimal
    income_tax_amount: Decimal


class DossierMovementRead(APIModel):
    movement_type: str
    amount: Decimal
    occurred_at: datetime
    reference: str | None = None
    # Presente cuando el cobro vino de la conciliación del extracto bancario.
    bank_reference: str | None = None


class DocumentDossierRead(APIModel):
    """Historia completa del comprobante: retenciones, cobros y saldo."""

    document_id: uuid.UUID
    doc_type: str
    direction: str
    access_key: str | None = None
    issue_date: date
    counterparty_name: str | None = None
    total: Decimal
    payment_methods: list[str]
    retentions: list[DossierRetentionRead]
    movements: list[DossierMovementRead]
    receivable_id: uuid.UUID | None = None
    receivable_status: str | None = None
    retained_iva: Decimal
    retained_income_tax: Decimal
    collected_amount: Decimal
    outstanding_amount: Decimal
    # total − retención IVA − retención renta
    expected_net: Decimal
    net_difference: Decimal
    notes: list[str]


class BulkItemRead(APIModel):
    """Una entrada del lote, ya clasificada por su contenido."""

    filename: str
    # Nombre del ZIP del que salió, si vino dentro de uno.
    source_archive: str | None = None
    status: str
    doc_type: str | None = None
    direction: str | None = None
    access_key: str | None = None
    issue_date: date | None = None
    # Periodo destino, calculado con la fecha real de emisión.
    period_year: int | None = None
    period_month: int | None = None
    counterparty_identification: str | None = None
    counterparty_name: str | None = None
    total: Decimal | None = None
    is_retention: bool = False
    error: str | None = None


class BulkResultRead(APIModel):
    """Resultado del previo o de la carga confirmada."""

    items: list[BulkItemRead]
    created: int
    updated: int
    duplicates: int
    errors: int
    # Comprobantes por periodo destino: {"2025-11": 4}
    periods: dict[str, int]
    notes: list[str]
    # Retenciones recibidas que podrían aplicarse a cartera.
    retention_count: int
    # Resultado de aplicar esas retenciones (solo si se pidió).
    retentions_applied: int = 0


class OwnDocumentsResultRead(APIModel):
    """Resultado de importar los comprobantes que la propia entidad emitió."""

    created: int
    updated: int
    # Comprobantes propios que no se pudieron importar (sin autorización o sin
    # XML firmado); el motivo va en `notes`.
    skipped: int
    notes: list[str]


class HistoricalTaxCandidateRead(APIModel):
    id: uuid.UUID
    document_number: str
    access_key: str
    issue_date: date
    customer_name: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    approved: bool
    xml_original_missing: bool = True


class HistoricalTaxExceptionApprove(APIModel):
    confirmed: bool
    evidence_reference: str = Field(min_length=8, max_length=500)


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
    payment_methods: list[str]
    is_preliminary: bool
    analytic_assignments: list[AnalyticAssignmentRead] = Field(default_factory=list)


class PurchaseTaxLineRead(APIModel):
    sri_tax_code: str
    tax_bracket: str
    rate: str
    base_amount: str
    tax_amount: str


class PurchaseDocumentRead(APIModel):
    id: uuid.UUID
    doc_type: str
    access_key: str | None = None
    issue_date: date
    document_number: str | None = None
    supplier_identification: str | None = None
    supplier_name: str | None = None
    subtotal: str
    tax_total: str
    total: str
    payment_methods: list[str]
    is_preliminary: bool
    taxes: list[PurchaseTaxLineRead]


class MonthlySalesTrendRead(APIModel):
    year: int
    month: int
    total: str
    invoice_count: int
    credit_note_count: int


class CurrentMonthTaxRead(APIModel):
    year: int
    month: int
    authorized_sales_total: str
    authorized_sales_count: int
    evidenced_sales_total: str
    evidenced_sales_count: int
    purchases_total: str
    purchase_count: int
    iva_generated: str
    iva_credit: str
    retained_iva: str
    iva_payable: str
    iva_credit_balance: str
    is_preliminary: bool
    preliminary_reasons: list[str]
    needs_accounting_review: bool


class DashboardTaxRead(APIModel):
    trend: list[MonthlySalesTrendRead]
    current_month: CurrentMonthTaxRead


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
    # Totales generales visibles en el TXT, solo como control hasta cargar XML.
    pending_purchase_count: int
    pending_purchase_subtotal: str
    pending_purchase_tax_total: str
    pending_purchase_total: str
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

"""Resumen de Tributario para lectura sin datos personales ni adjuntos."""

from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.base import APIModel


class _TaxReadModel(APIModel):
    model_config = ConfigDict(extra="forbid")


class RecordedTaxAmounts(_TaxReadModel):
    """USD, neto de notas de crédito. Las bases de compras no implican deducibilidad."""

    document_sales_subtotal: Decimal
    document_purchases_subtotal: Decimal
    iva_sales_base: Decimal
    iva_purchases_base: Decimal
    received_income_tax_withheld: Decimal
    received_iva_withheld: Decimal
    received_isd_withheld: Decimal


class ClassifiedPurchases(_TaxReadModel):
    """Bases por fecha de emisión según la clasificación del avance fiscal anual."""

    deductible_purchases_base: Decimal
    non_deductible_purchases_base: Decimal
    pending_review_purchases_base: Decimal


class TaxSummaryMonth(_TaxReadModel):
    month: int = Field(ge=1, le=12)
    iva_period_status: str | None
    filing_receipt_on_file: bool
    document_count: int
    preliminary: bool
    requires_external_review: bool
    classified_purchases: ClassifiedPurchases | None
    recorded: RecordedTaxAmounts | None
    filed_amounts: None = Field(
        description=(
            "Los valores efectivamente presentados no están almacenados en forma estructurada."
        )
    )


class TaxMonthlySummary(_TaxReadModel):
    year: int
    start_month: int = Field(ge=1, le=12)
    end_month: int = Field(ge=1, le=12)
    currency: Literal["USD"] = "USD"
    months: list[TaxSummaryMonth] = Field(min_length=1, max_length=12)
    classified_purchases_totals: ClassifiedPurchases | None
    recorded_totals: RecordedTaxAmounts | None
    months_with_document_data: int
    limitations: list[str]

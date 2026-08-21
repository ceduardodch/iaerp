"""Lecturas mensuales de ventas, compras e IVA respaldadas por documentos."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.tax import FiscalDocument, FiscalDocumentTax, TaxPeriod
from app.services.tax.completeness import missing_tax_detail_document_ids
from app.services.tax.iva import compute_iva

_PURCHASE_DOCUMENT_TYPES = ("FACTURA", "NOTA_CREDITO", "NOTA_DEBITO", "LIQUIDACION")
_ADDITIVE_DOCUMENT_TYPES = ("FACTURA", "NOTA_DEBITO", "LIQUIDACION")


@dataclass(frozen=True)
class PurchaseTaxLine:
    sri_tax_code: str
    tax_bracket: str
    rate: Decimal
    base_amount: Decimal
    tax_amount: Decimal


@dataclass(frozen=True)
class PurchaseRecord:
    id: uuid.UUID
    doc_type: str
    access_key: str | None
    issue_date: date
    document_number: str | None
    supplier_identification: str | None
    supplier_name: str | None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    payment_methods: list[str]
    is_preliminary: bool
    taxes: list[PurchaseTaxLine] = field(default_factory=list)


@dataclass(frozen=True)
class SalesTrendPoint:
    year: int
    month: int
    total: Decimal
    invoice_count: int
    credit_note_count: int


@dataclass(frozen=True)
class CurrentMonthSnapshot:
    year: int
    month: int
    authorized_sales_total: Decimal
    authorized_sales_count: int
    evidenced_sales_total: Decimal
    evidenced_sales_count: int
    purchases_total: Decimal
    purchase_count: int
    iva_generated: Decimal
    iva_credit: Decimal
    retained_iva: Decimal
    iva_payable: Decimal
    iva_credit_balance: Decimal
    is_preliminary: bool
    preliminary_reasons: list[str]
    needs_accounting_review: bool


@dataclass(frozen=True)
class DashboardTaxReport:
    trend: list[SalesTrendPoint]
    current_month: CurrentMonthSnapshot


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def _signed_amount(document: FiscalDocument) -> Decimal:
    if document.doc_type == "NOTA_CREDITO":
        return -document.total
    if document.doc_type in _ADDITIVE_DOCUMENT_TYPES:
        return document.total
    return Decimal("0.00")


def _document_number(document: FiscalDocument) -> str | None:
    parts = (
        document.establishment_code,
        document.emission_point_code,
        document.sequential,
    )
    if all(parts):
        return "-".join(str(part) for part in parts)
    return None


async def list_purchases(
    session: AsyncSession,
    context: AuthContext,
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[PurchaseRecord]:
    """Lista compras creadas desde evidencia recibida, con su desglose real."""
    query = select(FiscalDocument).where(
        FiscalDocument.tenant_id == context.tenant_id,
        FiscalDocument.direction == "RECIBIDO",
        FiscalDocument.doc_type.in_(_PURCHASE_DOCUMENT_TYPES),
    )
    if year is not None:
        query = query.where(
            FiscalDocument.issue_date >= date(year, month or 1, 1),
            FiscalDocument.issue_date
            < (date(year + 1, 1, 1) if month is None else _shift_month(date(year, month, 1), 1)),
        )
    documents = list(
        await session.scalars(
            query.order_by(FiscalDocument.issue_date.desc(), FiscalDocument.access_key.desc())
        )
    )
    if not documents:
        return []

    document_ids = [document.id for document in documents]
    tax_rows = list(
        await session.scalars(
            select(FiscalDocumentTax)
            .where(
                FiscalDocumentTax.tenant_id == context.tenant_id,
                FiscalDocumentTax.fiscal_document_id.in_(document_ids),
            )
            .order_by(FiscalDocumentTax.rate.desc(), FiscalDocumentTax.sri_tax_code)
        )
    )
    taxes_by_document: dict[uuid.UUID, list[PurchaseTaxLine]] = {}
    for row in tax_rows:
        taxes_by_document.setdefault(row.fiscal_document_id, []).append(
            PurchaseTaxLine(
                sri_tax_code=row.sri_tax_code,
                tax_bracket=row.tax_bracket,
                rate=row.rate,
                base_amount=row.base_amount,
                tax_amount=row.tax_amount,
            )
        )
    missing_tax_detail_ids = missing_tax_detail_document_ids(
        documents, set(taxes_by_document)
    )
    return [
        PurchaseRecord(
            id=document.id,
            doc_type=document.doc_type,
            access_key=document.access_key,
            issue_date=document.issue_date,
            document_number=_document_number(document),
            supplier_identification=document.counterparty_identification,
            supplier_name=document.counterparty_name,
            subtotal=document.subtotal,
            tax_total=document.tax_total,
            total=document.total,
            payment_methods=list(document.payment_methods or []),
            is_preliminary=(
                document.is_preliminary or document.id in missing_tax_detail_ids
            ),
            taxes=taxes_by_document.get(document.id, []),
        )
        for document in documents
    ]


async def dashboard_tax_report(
    session: AsyncSession,
    context: AuthContext,
    *,
    as_of: date,
    months: int,
) -> DashboardTaxReport:
    """Arma la evolución operativa y el corte tributario del mes actual."""
    current_start = _month_start(as_of)
    range_start = _shift_month(current_start, -(months - 1))
    range_end = _shift_month(current_start, 1)
    sales_documents = list(
        await session.scalars(
            select(SalesDocument).where(
                SalesDocument.tenant_id == context.tenant_id,
                SalesDocument.status.in_(("AUTHORIZED", "HISTORICAL_ISSUED")),
                SalesDocument.issue_date >= range_start,
                SalesDocument.issue_date < range_end,
            )
        )
    )
    trend_by_month = {
        (point.year, point.month): point
        for point in (
            SalesTrendPoint(
                year=value.year,
                month=value.month,
                total=Decimal("0.00"),
                invoice_count=0,
                credit_note_count=0,
            )
            for value in (_shift_month(range_start, index) for index in range(months))
        )
    }
    mutable_trend: dict[tuple[int, int], dict[str, Decimal | int]] = {
        key: {
            "total": point.total,
            "invoice_count": point.invoice_count,
            "credit_note_count": point.credit_note_count,
        }
        for key, point in trend_by_month.items()
    }
    for document in sales_documents:
        values = mutable_trend[(document.issue_date.year, document.issue_date.month)]
        if document.document_type == "CREDIT_NOTE":
            values["total"] = Decimal(str(values["total"])) - document.total
            values["credit_note_count"] = int(values["credit_note_count"]) + 1
        else:
            values["total"] = Decimal(str(values["total"])) + document.total
            values["invoice_count"] = int(values["invoice_count"]) + 1
    trend = [
        SalesTrendPoint(
            year=year,
            month=month,
            total=Decimal(str(values["total"])),
            invoice_count=int(values["invoice_count"]),
            credit_note_count=int(values["credit_note_count"]),
        )
        for (year, month), values in mutable_trend.items()
    ]

    current_sales = [
        document
        for document in sales_documents
        if document.status == "AUTHORIZED"
        and document.issue_date.year == as_of.year
        and document.issue_date.month == as_of.month
    ]
    authorized_sales_ids = {document.id for document in current_sales}
    authorized_sales_total = sum(
        (
            -document.total if document.document_type == "CREDIT_NOTE" else document.total
            for document in current_sales
        ),
        Decimal("0.00"),
    )
    authorized_sales_count = sum(
        1 for document in current_sales if document.document_type != "CREDIT_NOTE"
    )
    period = await session.scalar(
        select(TaxPeriod).where(
            TaxPeriod.tenant_id == context.tenant_id,
            TaxPeriod.year == as_of.year,
            TaxPeriod.month == as_of.month,
            TaxPeriod.obligation_type == "IVA",
        )
    )
    if period is None:
        current = CurrentMonthSnapshot(
            year=as_of.year,
            month=as_of.month,
            authorized_sales_total=authorized_sales_total,
            authorized_sales_count=authorized_sales_count,
            evidenced_sales_total=Decimal("0.00"),
            evidenced_sales_count=0,
            purchases_total=Decimal("0.00"),
            purchase_count=0,
            iva_generated=Decimal("0.00"),
            iva_credit=Decimal("0.00"),
            retained_iva=Decimal("0.00"),
            iva_payable=Decimal("0.00"),
            iva_credit_balance=Decimal("0.00"),
            is_preliminary=True,
            preliminary_reasons=[
                "El mes no tiene un periodo IVA con evidencia cargada."
            ],
            needs_accounting_review=False,
        )
        return DashboardTaxReport(trend=trend, current_month=current)

    fiscal_documents = list(
        await session.scalars(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.tax_period_id == period.id,
            )
        )
    )
    summary = await compute_iva(session, context, period=period)
    evidenced_sales = [
        document
        for document in fiscal_documents
        if document.direction == "EMITIDO" and document.doc_type != "RETENCION"
    ]
    purchases = [
        document
        for document in fiscal_documents
        if document.direction == "RECIBIDO" and document.doc_type in _PURCHASE_DOCUMENT_TYPES
    ]
    linked_sales_ids = {
        document.sales_document_id
        for document in evidenced_sales
        if document.sales_document_id is not None
    }
    missing_sales = authorized_sales_ids - linked_sales_ids
    reasons = list(summary.preliminary_reasons)
    if missing_sales:
        reasons.append(
            f"Falta importar {len(missing_sales)} comprobante(s) emitido(s) "
            "autorizado(s) del mes a Tributario."
        )
    iva_credit = summary.value("iva_credito_tributario")
    needs_accounting_review = iva_credit != Decimal("0.00")
    if needs_accounting_review:
        reasons.append(
            "El crédito de IVA debe validarse con el campo 564 y su respaldo contable."
        )
    current = CurrentMonthSnapshot(
        year=as_of.year,
        month=as_of.month,
        authorized_sales_total=authorized_sales_total,
        authorized_sales_count=authorized_sales_count,
        evidenced_sales_total=sum(
            (_signed_amount(document) for document in evidenced_sales), Decimal("0.00")
        ),
        evidenced_sales_count=len(evidenced_sales),
        purchases_total=sum(
            (_signed_amount(document) for document in purchases), Decimal("0.00")
        ),
        purchase_count=len(purchases),
        iva_generated=summary.value("iva_generado"),
        iva_credit=iva_credit,
        retained_iva=summary.value("retenciones_iva_recibidas"),
        iva_payable=summary.value("saldo_a_pagar"),
        iva_credit_balance=summary.value("credito_a_favor"),
        is_preliminary=summary.is_preliminary or bool(missing_sales) or needs_accounting_review,
        preliminary_reasons=reasons,
        needs_accounting_review=needs_accounting_review,
    )
    return DashboardTaxReport(trend=trend, current_month=current)


__all__ = [
    "CurrentMonthSnapshot",
    "DashboardTaxReport",
    "PurchaseRecord",
    "PurchaseTaxLine",
    "SalesTrendPoint",
    "dashboard_tax_report",
    "list_purchases",
]

"""Lecturas mensuales de ventas, compras e IVA respaldadas por documentos."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.payables import Payable
from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxPeriod
from app.services.tax.completeness import missing_tax_detail_document_ids
from app.services.tax.iva import compute_iva

_PURCHASE_DOCUMENT_TYPES = ("FACTURA", "NOTA_CREDITO", "NOTA_DEBITO", "LIQUIDACION")
_ADDITIVE_DOCUMENT_TYPES = ("FACTURA", "NOTA_DEBITO", "LIQUIDACION")
_MONEY_QUANTUM = Decimal("0.01")


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
class AnnualFiscalMonth:
    month: int
    status: str
    is_declared: bool
    sales_base: Decimal
    deductible_purchases_base: Decimal
    income_tax_withheld: Decimal


@dataclass(frozen=True)
class AnnualFiscalSnapshot:
    year: int
    sales_base: Decimal
    deductible_purchases_base: Decimal
    non_deductible_purchases_base: Decimal
    pending_review_purchases_base: Decimal
    internal_real_expenses_total: Decimal
    internal_real_expense_count: int
    internal_declaration_only_expenses_total: Decimal
    internal_declaration_only_expense_count: int
    internal_pending_expenses_total: Decimal
    internal_pending_expense_count: int
    result_before_adjustments: Decimal
    income_tax_withheld: Decimal
    iva_withheld: Decimal
    declared_sales_base: Decimal
    declared_deductible_purchases_base: Decimal
    declared_result_before_adjustments: Decimal
    declared_income_tax_withheld: Decimal
    declared_month_count: int
    last_declared_month: int | None
    estimated_income_tax_rate: Decimal | None
    declared_estimated_income_tax: Decimal | None
    projected_estimated_income_tax: Decimal | None
    declared_estimated_balance: Decimal | None
    projected_estimated_balance: Decimal | None
    estimate_reason: str
    pending_review_document_count: int
    preliminary_document_count: int
    refund_status: Literal["REVIEW_AT_ANNUAL_CLOSE", "NO_RECORDED_CREDIT"]
    refund_message: str
    limitations: list[str]
    months: list[AnnualFiscalMonth]


@dataclass(frozen=True)
class DashboardTaxReport:
    trend: list[SalesTrendPoint]
    current_month: CurrentMonthSnapshot
    annual: AnnualFiscalSnapshot


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


def _signed_subtotal(document: FiscalDocument) -> Decimal:
    if document.doc_type == "NOTA_CREDITO":
        return -document.subtotal
    if document.doc_type in _ADDITIVE_DOCUMENT_TYPES:
        return document.subtotal
    return Decimal("0.00")


def _estimate_income_tax(base: Decimal, rate: Decimal) -> Decimal:
    return (max(base, Decimal("0.00")) * rate / Decimal("100")).quantize(
        _MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


async def _annual_fiscal_snapshot(
    session: AsyncSession,
    context: AuthContext,
    *,
    as_of: date,
    sales_documents: list[SalesDocument],
    income_tax_rate: Decimal | None,
) -> AnnualFiscalSnapshot:
    """Resume el año hasta el mes elegido, sin simular una declaración anual."""
    year = as_of.year
    year_start = date(year, 1, 1)
    cutoff = _shift_month(_month_start(as_of), 1)
    periods = list(
        await session.scalars(
            select(TaxPeriod).where(
                TaxPeriod.tenant_id == context.tenant_id,
                TaxPeriod.year == year,
                TaxPeriod.month <= as_of.month,
                TaxPeriod.obligation_type == "IVA",
            )
        )
    )
    period_status_by_month = {period.month: period.status for period in periods}
    declared_period_ids = {
        period.id for period in periods if period.status == "DECLARADO"
    }
    declared_months = {
        period.month for period in periods if period.status == "DECLARADO"
    }
    annual_sales = [
        document
        for document in sales_documents
        if year_start <= document.issue_date < cutoff
    ]
    purchase_documents = list(
        await session.scalars(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.direction == "RECIBIDO",
                FiscalDocument.doc_type.in_(_PURCHASE_DOCUMENT_TYPES),
                FiscalDocument.issue_date >= year_start,
                FiscalDocument.issue_date < cutoff,
            )
        )
    )
    declared_sales_documents = (
        list(
            await session.scalars(
                select(FiscalDocument).where(
                    FiscalDocument.tenant_id == context.tenant_id,
                    FiscalDocument.direction == "EMITIDO",
                    FiscalDocument.doc_type != "RETENCION",
                    FiscalDocument.tax_period_id.in_(declared_period_ids),
                )
            )
        )
        if declared_period_ids
        else []
    )
    source_keys = {
        document.related_access_key
        for document in purchase_documents
        if document.doc_type == "NOTA_CREDITO" and document.related_access_key
    }
    source_documents = (
        list(
            await session.scalars(
                select(FiscalDocument).where(
                    FiscalDocument.tenant_id == context.tenant_id,
                    FiscalDocument.access_key.in_(source_keys),
                )
            )
        )
        if source_keys
        else []
    )
    source_by_key = {
        document.access_key: document for document in source_documents if document.access_key
    }
    payable_document_ids = {
        document.id for document in purchase_documents
    } | {document.id for document in source_documents}
    payables = (
        list(
            await session.scalars(
                select(Payable).where(
                    Payable.tenant_id == context.tenant_id,
                    Payable.fiscal_document_id.in_(payable_document_ids),
                )
            )
        )
        if payable_document_ids
        else []
    )
    payable_by_document = {
        payable.fiscal_document_id: payable
        for payable in payables
        if payable.fiscal_document_id is not None
    }
    annual_operational_payables = list(
        await session.scalars(
            select(Payable).where(
                Payable.tenant_id == context.tenant_id,
                Payable.issue_date >= year_start,
                Payable.issue_date < cutoff,
                Payable.status != "VOID",
            )
        )
    )
    internal_real_expenses_total = sum(
        (
            payable.total
            for payable in annual_operational_payables
            if payable.internal_classification == "REAL"
        ),
        Decimal("0.00"),
    )
    internal_real_expense_count = sum(
        payable.internal_classification == "REAL"
        for payable in annual_operational_payables
    )
    internal_declaration_only_expenses_total = sum(
        (
            payable.total
            for payable in annual_operational_payables
            if payable.internal_classification == "DECLARATION_ONLY"
        ),
        Decimal("0.00"),
    )
    internal_declaration_only_expense_count = sum(
        payable.internal_classification == "DECLARATION_ONLY"
        for payable in annual_operational_payables
    )
    internal_pending_expenses_total = sum(
        (
            payable.total
            for payable in annual_operational_payables
            if payable.internal_classification == "PENDING_REVIEW"
        ),
        Decimal("0.00"),
    )
    internal_pending_expense_count = sum(
        payable.internal_classification == "PENDING_REVIEW"
        for payable in annual_operational_payables
    )

    purchase_totals = {
        "DEDUCTIBLE_CONFIRMED": Decimal("0.00"),
        "NON_DEDUCTIBLE": Decimal("0.00"),
        "DEDUCTIBLE_PENDING_REVIEW": Decimal("0.00"),
    }
    pending_count = 0
    for document in purchase_documents:
        payable = payable_by_document.get(document.id)
        if payable is None and document.doc_type == "NOTA_CREDITO":
            source = (
                source_by_key.get(document.related_access_key)
                if document.related_access_key
                else None
            )
            if source is not None:
                payable = payable_by_document.get(source.id)
        classification = (
            payable.tax_classification
            if payable is not None
            else "DEDUCTIBLE_PENDING_REVIEW"
        )
        if classification not in purchase_totals:
            classification = "DEDUCTIBLE_PENDING_REVIEW"
        purchase_totals[classification] += _signed_subtotal(document)
        if classification == "DEDUCTIBLE_PENDING_REVIEW":
            pending_count += 1

    retention_rows = list(
        await session.execute(
            select(FiscalRetention, FiscalDocument)
            .join(
                FiscalDocument,
                (FiscalDocument.id == FiscalRetention.fiscal_document_id)
                & (FiscalDocument.tenant_id == FiscalRetention.tenant_id),
            )
            .where(
                FiscalRetention.tenant_id == context.tenant_id,
                FiscalDocument.direction == "RECIBIDO",
                FiscalDocument.issue_date >= year_start,
                FiscalDocument.issue_date < cutoff,
            )
        )
    )
    income_tax_withheld = sum(
        (retention.retained_amount for retention, _ in retention_rows if retention.kind == "RENTA"),
        Decimal("0.00"),
    )
    iva_withheld = sum(
        (retention.retained_amount for retention, _ in retention_rows if retention.kind == "IVA"),
        Decimal("0.00"),
    )
    deductible = purchase_totals["DEDUCTIBLE_CONFIRMED"]
    sales_base = sum(
        (
            -document.subtotal
            if document.document_type == "CREDIT_NOTE"
            else document.subtotal
            for document in annual_sales
        ),
        Decimal("0.00"),
    )
    monthly_sales = {month: Decimal("0.00") for month in range(1, 13)}
    monthly_deductible = {month: Decimal("0.00") for month in range(1, 13)}
    monthly_income_withheld = {month: Decimal("0.00") for month in range(1, 13)}
    for sales_document in annual_sales:
        monthly_sales[sales_document.issue_date.month] += (
            -sales_document.subtotal
            if sales_document.document_type == "CREDIT_NOTE"
            else sales_document.subtotal
        )
    for document in purchase_documents:
        payable = payable_by_document.get(document.id)
        if payable is None and document.doc_type == "NOTA_CREDITO":
            source = (
                source_by_key.get(document.related_access_key)
                if document.related_access_key
                else None
            )
            if source is not None:
                payable = payable_by_document.get(source.id)
        if payable is not None and payable.tax_classification == "DEDUCTIBLE_CONFIRMED":
            monthly_deductible[document.issue_date.month] += _signed_subtotal(document)
    for retention, retention_document in retention_rows:
        if retention.kind == "RENTA":
            monthly_income_withheld[retention_document.issue_date.month] += (
                retention.retained_amount
            )

    declared_purchase_documents = [
        document
        for document in purchase_documents
        if document.tax_period_id in declared_period_ids
    ]
    declared_deductible = Decimal("0.00")
    for document in declared_purchase_documents:
        payable = payable_by_document.get(document.id)
        if payable is None and document.doc_type == "NOTA_CREDITO":
            source = (
                source_by_key.get(document.related_access_key)
                if document.related_access_key
                else None
            )
            if source is not None:
                payable = payable_by_document.get(source.id)
        if payable is not None and payable.tax_classification == "DEDUCTIBLE_CONFIRMED":
            declared_deductible += _signed_subtotal(document)

    declared_sales_base = sum(
        (_signed_subtotal(document) for document in declared_sales_documents),
        Decimal("0.00"),
    )
    declared_income_tax_withheld = sum(
        (
            retention.retained_amount
            for retention, retention_document in retention_rows
            if retention.kind == "RENTA"
            and retention_document.tax_period_id in declared_period_ids
        ),
        Decimal("0.00"),
    )
    declared_result = declared_sales_base - declared_deductible
    projected_result = sales_base - deductible
    estimated_rate = (
        income_tax_rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if income_tax_rate is not None
        else None
    )
    if estimated_rate is None:
        declared_estimated_tax = None
        projected_estimated_tax = None
        declared_estimated_balance = None
        projected_estimated_balance = None
        estimate_reason = (
            "Selecciona un escenario de tarifa en pantalla para aproximar la renta. "
            "IAERP no infiere el régimen ni la tarifa a partir del RUC."
        )
    else:
        declared_estimated_tax = _estimate_income_tax(declared_result, estimated_rate)
        projected_estimated_tax = _estimate_income_tax(projected_result, estimated_rate)
        declared_estimated_balance = declared_estimated_tax - declared_income_tax_withheld
        projected_estimated_balance = projected_estimated_tax - income_tax_withheld
        estimate_reason = (
            f"Escenario manual al {estimated_rate.normalize()} %. No incluye conciliación "
            "tributaria ni ajustes del cierre y no es una liquidación del SRI."
        )

    refund_status: Literal["REVIEW_AT_ANNUAL_CLOSE", "NO_RECORDED_CREDIT"]
    if income_tax_withheld > Decimal("0.00"):
        refund_status = "REVIEW_AT_ANNUAL_CLOSE"
        refund_message = (
            "Hay retenciones de renta registradas en el año. Solo existe un posible "
            "saldo a favor si, al declarar el año, superan el impuesto causado."
        )
    else:
        refund_status = "NO_RECORDED_CREDIT"
        refund_message = "No hay retenciones de renta registradas para evaluar un saldo a favor."

    limitations = [
        "El resultado no incluye conciliación tributaria, participación laboral, "
        "depreciaciones ni otros ajustes contables.",
        estimate_reason,
    ]
    if pending_count:
        limitations.insert(
            0,
            f"Hay {pending_count} compra(s) pendientes de confirmar como deducibles "
            "o no deducibles.",
        )
    preliminary_retention_ids = {
        retention_document.id
        for _, retention_document in retention_rows
        if retention_document.is_preliminary
    }
    preliminary_count = (
        sum(1 for document in purchase_documents if document.is_preliminary)
        + len(preliminary_retention_ids)
    )
    if preliminary_count:
        limitations.insert(
            0,
            f"Hay {preliminary_count} comprobante(s) preliminar(es) sin respaldo completo.",
        )

    return AnnualFiscalSnapshot(
        year=year,
        sales_base=sales_base,
        deductible_purchases_base=deductible,
        non_deductible_purchases_base=purchase_totals["NON_DEDUCTIBLE"],
        pending_review_purchases_base=purchase_totals["DEDUCTIBLE_PENDING_REVIEW"],
        internal_real_expenses_total=internal_real_expenses_total,
        internal_real_expense_count=internal_real_expense_count,
        internal_declaration_only_expenses_total=(
            internal_declaration_only_expenses_total
        ),
        internal_declaration_only_expense_count=(
            internal_declaration_only_expense_count
        ),
        internal_pending_expenses_total=internal_pending_expenses_total,
        internal_pending_expense_count=internal_pending_expense_count,
        result_before_adjustments=projected_result,
        income_tax_withheld=income_tax_withheld,
        iva_withheld=iva_withheld,
        declared_sales_base=declared_sales_base,
        declared_deductible_purchases_base=declared_deductible,
        declared_result_before_adjustments=declared_result,
        declared_income_tax_withheld=declared_income_tax_withheld,
        declared_month_count=len(declared_months),
        last_declared_month=max(declared_months) if declared_months else None,
        estimated_income_tax_rate=estimated_rate,
        declared_estimated_income_tax=declared_estimated_tax,
        projected_estimated_income_tax=projected_estimated_tax,
        declared_estimated_balance=declared_estimated_balance,
        projected_estimated_balance=projected_estimated_balance,
        estimate_reason=estimate_reason,
        pending_review_document_count=pending_count,
        preliminary_document_count=preliminary_count,
        refund_status=refund_status,
        refund_message=refund_message,
        limitations=limitations,
        months=[
            AnnualFiscalMonth(
                month=month,
                status=period_status_by_month.get(month, "SIN_PERIODO"),
                is_declared=month in declared_months,
                sales_base=monthly_sales[month],
                deductible_purchases_base=monthly_deductible[month],
                income_tax_withheld=monthly_income_withheld[month],
            )
            for month in range(1, 13)
        ],
    )


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
    income_tax_rate: Decimal | None = None,
) -> DashboardTaxReport:
    """Arma la evolución operativa y el corte tributario del mes actual."""
    current_start = _month_start(as_of)
    range_start = _shift_month(current_start, -(months - 1))
    range_end = _shift_month(current_start, 1)
    sales_range_start = min(range_start, date(as_of.year, 1, 1))
    sales_range_end = range_end
    sales_documents = list(
        await session.scalars(
            select(SalesDocument).where(
                SalesDocument.tenant_id == context.tenant_id,
                SalesDocument.status.in_(("AUTHORIZED", "HISTORICAL_ISSUED")),
                SalesDocument.issue_date >= sales_range_start,
                SalesDocument.issue_date < sales_range_end,
            )
        )
    )
    annual = await _annual_fiscal_snapshot(
        session,
        context,
        as_of=as_of,
        sales_documents=sales_documents,
        income_tax_rate=income_tax_rate,
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
        if not (range_start <= document.issue_date < range_end):
            continue
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
        return DashboardTaxReport(trend=trend, current_month=current, annual=annual)

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
    return DashboardTaxReport(trend=trend, current_month=current, annual=annual)


__all__ = [
    "AnnualFiscalMonth",
    "AnnualFiscalSnapshot",
    "CurrentMonthSnapshot",
    "DashboardTaxReport",
    "PurchaseRecord",
    "PurchaseTaxLine",
    "SalesTrendPoint",
    "dashboard_tax_report",
    "list_purchases",
]

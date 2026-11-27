"""Resumen de solo lectura del expediente de IVA por período fiscal."""

from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument, TaxEvidence, TaxPeriod
from app.schemas.tax_monthly_summary import (
    ClassifiedPurchases,
    RecordedTaxAmounts,
    TaxMonthlySummary,
    TaxSummaryMonth,
)
from app.services.tax.due_dates import declaration_month
from app.services.tax.external_purchases import external_payment_details
from app.services.tax.iva import compute_iva
from app.services.tax.reporting import classified_purchase_bases

_ZERO = Decimal("0.00")


async def read_monthly_summary(
    session: AsyncSession,
    context: AuthContext,
    *,
    year: int,
    start_month: int,
    end_month: int,
) -> TaxMonthlySummary:
    if not 2000 <= year <= 2100 or not 1 <= start_month <= end_month <= 12:
        raise ValueError("Elige un año entre 2000 y 2100 y meses consecutivos del 1 al 12.")

    periods = {
        period.month: period
        for period in await session.scalars(
            select(TaxPeriod).where(
                TaxPeriod.tenant_id == context.tenant_id,
                TaxPeriod.obligation_type == "IVA",
                TaxPeriod.year == year,
                TaxPeriod.month.between(start_month, end_month),
            )
        )
    }
    period_ids = [period.id for period in periods.values()]
    receipts = set(
        await session.scalars(
            select(TaxEvidence.tax_period_id)
            .distinct()
            .where(
                TaxEvidence.tenant_id == context.tenant_id,
                TaxEvidence.tax_period_id.in_(period_ids),
                TaxEvidence.origin == "ACUSE_IVA_SRI",
                TaxEvidence.file_type == "PDF",
            )
        )
    )
    signed = case(
        (FiscalDocument.doc_type == "NOTA_CREDITO", -FiscalDocument.subtotal),
        else_=FiscalDocument.subtotal,
    )
    purchase = (FiscalDocument.direction == "RECIBIDO") | FiscalDocument.is_issued_purchase
    rows = await session.execute(
        select(
            FiscalDocument.tax_period_id,
            func.sum(case((purchase, _ZERO), else_=signed)),
            func.sum(case((purchase, signed), else_=_ZERO)),
        )
        .where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.tax_period_id.in_(period_ids),
            FiscalDocument.doc_type.in_(("FACTURA", "NOTA_DEBITO", "NOTA_CREDITO", "LIQUIDACION")),
            FiscalDocument.cancelled_at.is_(None),
        )
        .group_by(FiscalDocument.tax_period_id)
    )
    document_bases = {
        period_id: (Decimal(sales).quantize(_ZERO), Decimal(purchases).quantize(_ZERO))
        for period_id, sales, purchases in rows
    }
    classified_bases = await classified_purchase_bases(
        session,
        context,
        from_date=date(year, start_month, 1),
        until_date=date(*declaration_month(year=year, month=end_month), 1),
    )
    classified_by_month: dict[int, ClassifiedPurchases] = {}
    empty = ClassifiedPurchases(
        deductible_purchases_base=_ZERO,
        non_deductible_purchases_base=_ZERO,
        pending_review_purchases_base=_ZERO,
    )
    for purchase_base in classified_bases:
        monthly = classified_by_month.get(purchase_base.month)
        if monthly is None:
            monthly = empty.model_copy()
            classified_by_month[purchase_base.month] = monthly
        if purchase_base.classification == "DEDUCTIBLE_CONFIRMED":
            monthly.deductible_purchases_base += purchase_base.base
        elif purchase_base.classification == "NON_DEDUCTIBLE":
            monthly.non_deductible_purchases_base += purchase_base.base
        else:
            monthly.pending_review_purchases_base += purchase_base.base

    months = []
    recorded_months = []
    for month in range(start_month, end_month + 1):
        period = periods.get(month)
        if period is None:
            external = await external_payment_details(
                session, tenant_id=context.tenant_id, year=year, month=month
            )
            months.append(
                TaxSummaryMonth(
                    month=month,
                    iva_period_status=None,
                    filing_receipt_on_file=False,
                    document_count=0,
                    preliminary=True,
                    requires_external_review=bool(external),
                    classified_purchases=classified_by_month.get(month),
                    recorded=None,
                    filed_amounts=None,
                )
            )
            continue

        iva = await compute_iva(session, context, period=period)
        recorded = None
        if iva.document_count:
            sales, purchases = document_bases.get(period.id, (_ZERO, _ZERO))
            recorded = RecordedTaxAmounts(
                document_sales_subtotal=sales,
                document_purchases_subtotal=purchases,
                iva_sales_base=iva.value("ventas_netas"),
                iva_purchases_base=iva.value("compras_totales_base"),
                received_income_tax_withheld=iva.value("retenciones_renta_recibidas"),
                received_iva_withheld=iva.value("retenciones_iva_recibidas"),
                received_isd_withheld=iva.value("retenciones_isd_recibidas"),
            )
            recorded_months.append(recorded)
        months.append(
            TaxSummaryMonth(
                month=month,
                iva_period_status=period.status,
                filing_receipt_on_file=period.id in receipts,
                document_count=iva.document_count,
                preliminary=iva.is_preliminary,
                requires_external_review=iva.requires_external_review,
                classified_purchases=classified_by_month.get(
                    month, empty if iva.document_count else None
                ),
                recorded=recorded,
                filed_amounts=None,
            )
        )

    totals = None
    if recorded_months:
        totals = RecordedTaxAmounts(
            **{
                key: sum((getattr(month_data, key) for month_data in recorded_months), _ZERO)
                for key in RecordedTaxAmounts.model_fields
            }
        )
    classifications = [m.classified_purchases for m in months if m.classified_purchases is not None]
    classified_totals = None
    if classifications:
        classified_totals = ClassifiedPurchases(
            **{
                key: sum((getattr(item, key) for item in classifications), _ZERO)
                for key in ClassifiedPurchases.model_fields
            }
        )
    return TaxMonthlySummary(
        year=year,
        start_month=start_month,
        end_month=end_month,
        months=months,
        recorded_totals=totals,
        classified_purchases_totals=classified_totals,
        months_with_document_data=len(recorded_months),
        limitations=[
            "Los subtotales son los de los comprobantes fiscales activos vinculados al período, "
            "netos de notas de crédito y sin IVA. Las compras incluyen liquidaciones emitidas "
            "y sus notas.",
            "Las ventas documentales son las evidenciadas en Tributario. El avance mensual "
            "de ventas operativo usa las facturas y notas autorizadas o históricas por emisión.",
            "Las bases de IVA se calculan con el desglose de los comprobantes. "
            "Los períodos preliminares y los servicios del exterior pueden requerir conciliación.",
            "Las compras clasificadas son las del avance fiscal anual por mes de emisión. "
            "Las notas de crédito restan y pueden heredar la clasificación de la compra original.",
            "Los totales suman solo los meses con comprobantes. La falta de documentos "
            "no acredita un mes sin actividad.",
            "El estado de IVA y la existencia de un acuse PDF se informan por separado. "
            "Los importes presentados en el 104 requieren cotejar el formulario del SRI.",
            "La clasificación refleja el criterio registrado. Para determinar la utilidad contable "
            "y el impuesto a la renta anual se requiere la conciliación de cierre.",
        ],
    )

"""La consulta fiscal conserva el origen, el signo y el ámbito de cada importe."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.db.session import SessionFactory, engine
from app.models.payables import Payable
from app.models.tax import (
    FiscalDocument,
    FiscalDocumentTax,
    FiscalRetention,
    TaxEvidence,
    TaxPeriod,
)
from app.services.tax.monthly_summary import read_monthly_summary
from app.services.tax.reporting import dashboard_tax_report
from tests.conftest import TENANT_A, TENANT_B
from tests.test_tax_due_dates import context_for


async def test_monthly_summary_distinguishes_filing_from_evidence_and_performs_only_reads():
    async with SessionFactory() as session, session.begin():
        first = TaxPeriod(
            tenant_id=TENANT_A, year=2026, month=1, obligation_type="IVA", status="DECLARADO"
        )
        second = TaxPeriod(
            tenant_id=TENANT_A,
            year=2026,
            month=2,
            obligation_type="IVA",
            status="PENDIENTE_DESCARGA",
        )
        other = TaxPeriod(
            tenant_id=TENANT_B, year=2026, month=1, obligation_type="IVA", status="DECLARADO"
        )
        session.add_all([first, second, other])
        await session.flush()

        def receipt(period, digest, origin):
            return TaxEvidence(
                tenant_id=period.tenant_id,
                tax_period_id=period.id,
                filename="prueba.pdf",
                file_type="PDF",
                object_key="privado",
                sha256=digest * 64,
                size_bytes=1,
                origin=origin,
                uploaded_at=datetime.now(UTC),
            )

        session.add_all(
            [
                receipt(first, "1", "MANUAL"),
                receipt(second, "2", "ACUSE_IVA_SRI"),
                receipt(other, "3", "ACUSE_IVA_SRI"),
            ]
        )

        def doc(period, direction, kind, base, **kwargs):
            return FiscalDocument(
                tenant_id=period.tenant_id,
                tax_period_id=period.id,
                direction=direction,
                doc_type=kind,
                issue_date=date(2026, 1, 20),
                subtotal=Decimal(base),
                **kwargs,
            )

        sale = doc(first, "EMITIDO", "FACTURA", "123.23")
        sale_credit = doc(first, "EMITIDO", "NOTA_CREDITO", "10.13")
        purchase = doc(first, "RECIBIDO", "FACTURA", "71.65")
        incomplete = doc(first, "RECIBIDO", "FACTURA", "8.10", is_preliminary=True)
        foreign = doc(first, "EMITIDO", "LIQUIDACION", "12.11")
        foreign_credit = doc(
            first, "EMITIDO", "NOTA_CREDITO", "0.42", related_document_type="LIQUIDACION"
        )
        withheld = doc(first, "RECIBIDO", "RETENCION", "0")
        issued_withholding = doc(first, "EMITIDO", "RETENCION", "0")
        session.add_all(
            [
                sale,
                sale_credit,
                purchase,
                incomplete,
                foreign,
                foreign_credit,
                withheld,
                issued_withholding,
                doc(other, "EMITIDO", "FACTURA", "999999"),
            ]
        )
        await session.flush()
        for evidenced in (sale, sale_credit, purchase, foreign, foreign_credit):
            session.add(
                FiscalDocumentTax(
                    tenant_id=TENANT_A,
                    fiscal_document_id=evidenced.id,
                    sri_tax_code="0",
                    tax_bracket="TARIFA_CERO",
                    base_amount=evidenced.subtotal,
                    tax_amount=Decimal("0"),
                )
            )
        for owner, kind, amount in [
            (withheld, "RENTA", "1.11"),
            (withheld, "IVA", "2.22"),
            (withheld, "ISD", "3.33"),
            (issued_withholding, "RENTA", "1000.00"),
        ]:
            session.add(
                FiscalRetention(
                    tenant_id=TENANT_A,
                    fiscal_document_id=owner.id,
                    kind=kind,
                    sri_code="001",
                    retained_amount=Decimal(amount),
                )
            )

    def reject_writes(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT"), statement

    event.listen(engine.sync_engine, "before_cursor_execute", reject_writes)
    try:
        async with SessionFactory() as session:
            report = await read_monthly_summary(
                session, context_for(TENANT_A), year=2026, start_month=1, end_month=3
            )
            dashboard = await dashboard_tax_report(
                session,
                context_for(TENANT_A),
                as_of=date(2026, 1, 31),
                months=1,
            )
            missing_report = await read_monthly_summary(
                session, context_for(TENANT_A), year=2026, start_month=3, end_month=3
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", reject_writes)

    a, b, c = report.months
    assert [a.month, b.month, c.month] == [1, 2, 3]
    assert (a.iva_period_status, a.filing_receipt_on_file, a.filed_amounts) == (
        "DECLARADO",
        False,
        None,
    )
    assert a.preliminary and a.requires_external_review and a.document_count == 8
    assert a.recorded and a.recorded.model_dump(mode="json") == {
        "documentSalesSubtotal": "113.10",
        "documentPurchasesSubtotal": "91.44",
        "ivaSalesBase": "113.10",
        "ivaPurchasesBase": "71.65",
        "receivedIncomeTaxWithheld": "1.11",
        "receivedIvaWithheld": "2.22",
        "receivedIsdWithheld": "3.33",
    }
    # Las ventas de este fixture son evidencia fiscal sin copia en facturación operativa.
    assert a.recorded.document_sales_subtotal == dashboard.annual.declared_sales_base
    assert dashboard.annual.months[0].sales_base == Decimal("0.00")
    assert (b.iva_period_status, b.filing_receipt_on_file, b.recorded, b.filed_amounts) == (
        "PENDIENTE_DESCARGA",
        True,
        None,
        None,
    )
    assert (c.iva_period_status, c.filing_receipt_on_file, c.recorded) == (None, False, None)
    assert report.recorded_totals == a.recorded
    assert report.months_with_document_data == 1
    assert missing_report.recorded_totals is None


@pytest.mark.parametrize(("year", "start", "end"), [(1999, 1, 1), (2026, 4, 3), (2026, 1, 13)])
async def test_monthly_summary_rejects_invalid_ranges(year, start, end):
    async with SessionFactory() as session:
        with pytest.raises(ValueError):
            await read_monthly_summary(
                session, context_for(TENANT_A), year=year, start_month=start, end_month=end
            )


async def test_summary_excludes_cancelled_purchase_and_uses_the_requested_period_range():
    async with SessionFactory() as session, session.begin():
        january, february, march = [
            TaxPeriod(tenant_id=TENANT_A, year=2026, month=month, obligation_type="IVA")
            for month in range(1, 4)
        ]
        session.add_all([january, february, march])
        await session.flush()
        evidence = TaxEvidence(
            tenant_id=TENANT_A,
            tax_period_id=february.id,
            filename="anulacion.pdf",
            file_type="PDF",
            object_key="privado",
            sha256="f" * 64,
            size_bytes=1,
            origin="MANUAL",
            uploaded_at=datetime.now(UTC),
        )
        session.add(evidence)
        await session.flush()
        for period, base in [(january, "10000"), (february, "100.31"), (march, "8.92")]:
            session.add(
                FiscalDocument(
                    tenant_id=TENANT_A,
                    tax_period_id=period.id,
                    issue_date=date(2026, period.month, 1),
                    doc_type="FACTURA",
                    direction="RECIBIDO",
                    subtotal=Decimal(base),
                    is_preliminary=True,
                )
            )
        session.add(
            FiscalDocument(
                tenant_id=TENANT_A,
                tax_period_id=february.id,
                issue_date=date(2026, 2, 1),
                doc_type="FACTURA",
                direction="RECIBIDO",
                subtotal=Decimal("65.50"),
                cancelled_at=datetime.now(UTC),
                cancellation_date=date(2026, 2, 2),
                cancellation_reason="Anulación documentada",
                cancellation_evidence_id=evidence.id,
                cancelled_by_actor_id="test",
            )
        )

    async with SessionFactory() as session:
        report = await read_monthly_summary(
            session, context_for(TENANT_A), year=2026, start_month=2, end_month=3
        )
    assert [(month.month, month.document_count) for month in report.months] == [(2, 1), (3, 1)]
    assert report.months_with_document_data == 2
    assert report.recorded_totals
    assert report.recorded_totals.document_purchases_subtotal == Decimal("109.23")
    assert report.recorded_totals.iva_purchases_base == Decimal("0.00")


async def test_classified_purchases_match_annual_progress_with_cross_month_credit():
    async with SessionFactory() as session, session.begin():

        def doc(month, kind, base, **extra):
            return FiscalDocument(
                tenant_id=TENANT_A,
                direction="RECIBIDO",
                doc_type=kind,
                issue_date=date(2026, month, 5),
                subtotal=Decimal(base),
                **extra,
            )

        key = "7" * 49
        original = doc(1, "FACTURA", "21.43", access_key=key)
        credit = doc(2, "NOTA_CREDITO", "2.13", related_access_key=key)
        pending = doc(2, "FACTURA", "8.13")
        non_deductible = doc(2, "FACTURA", "9.12")
        session.add_all([original, credit, pending, non_deductible])
        await session.flush()
        for purchase, classification in [
            (original, "DEDUCTIBLE_CONFIRMED"),
            (non_deductible, "NON_DEDUCTIBLE"),
        ]:
            session.add(
                Payable(
                    tenant_id=TENANT_A,
                    fiscal_document_id=purchase.id,
                    issue_date=purchase.issue_date,
                    due_date=purchase.issue_date,
                    description="Compra sintética",
                    total=purchase.subtotal,
                    tax_classification=classification,
                )
            )
    async with SessionFactory() as session:
        context = context_for(TENANT_A)
        dashboard = await dashboard_tax_report(session, context, as_of=date(2026, 2, 28), months=2)
        summary = await read_monthly_summary(
            session, context, year=2026, start_month=2, end_month=2
        )
        annual_to_date = await read_monthly_summary(
            session, context, year=2026, start_month=1, end_month=2
        )
    february = summary.months[0]
    # El avance por emisión puede existir aunque todavía falte el período de IVA.
    assert february.iva_period_status is None and february.recorded is None
    assert february.classified_purchases
    assert february.classified_purchases == summary.classified_purchases_totals
    assert february.classified_purchases.model_dump(mode="json") == {
        "deductiblePurchasesBase": "-2.13",
        "nonDeductiblePurchasesBase": "9.12",
        "pendingReviewPurchasesBase": "8.13",
    }
    annual = dashboard.annual
    assert february.classified_purchases.deductible_purchases_base == (
        annual.months[1].deductible_purchases_base
    )
    combined = annual_to_date.classified_purchases_totals
    assert combined and combined.deductible_purchases_base == annual.deductible_purchases_base
    assert combined.non_deductible_purchases_base == annual.non_deductible_purchases_base
    assert combined.pending_review_purchases_base == annual.pending_review_purchases_base

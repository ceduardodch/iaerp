import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.tax import FiscalDocument, TaxPeriod, TaxTask
from app.services.tax.tasks import generate_tax_tasks_once


async def test_tax_scheduler_creates_only_approval_required_tasks() -> None:
    async with SessionFactory() as session, session.begin():
        period = TaxPeriod(
            tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            year=2026,
            month=7,
            obligation_type="IVA",
            status="PENDIENTE_DESCARGA",
        )
        session.add(period)

    assert await generate_tax_tasks_once() == 1
    assert await generate_tax_tasks_once() == 0

    async with SessionFactory() as session:
        tasks = list(await session.scalars(select(TaxTask)))
    assert len(tasks) == 1
    assert tasks[0].task_type == "BAJAR_COMPROBANTES"
    assert tasks[0].requires_approval is True


async def test_tax_scheduler_requests_xml_when_tax_detail_rows_are_missing() -> None:
    tenant_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    async with SessionFactory() as session, session.begin():
        period = TaxPeriod(
            tenant_id=tenant_id,
            year=2026,
            month=8,
            obligation_type="IVA",
            status="LISTO_REVISAR",
        )
        session.add(period)
        await session.flush()
        session.add(
            FiscalDocument(
                tenant_id=tenant_id,
                tax_period_id=period.id,
                direction="RECIBIDO",
                doc_type="FACTURA",
                access_key="1" * 49,
                issue_date=date(2026, 8, 1),
                subtotal=Decimal("100.00"),
                tax_total=Decimal("15.00"),
                total=Decimal("115.00"),
                payment_methods=[],
                is_preliminary=False,
            )
        )

    assert await generate_tax_tasks_once() == 1

    async with SessionFactory() as session:
        tasks = list(
            await session.scalars(
                select(TaxTask).where(TaxTask.tax_period_id == period.id)
            )
        )
    assert len(tasks) == 1
    assert tasks[0].task_type == "COMPLETAR_EVIDENCIA"

import uuid

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.tax import TaxPeriod, TaxTask
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

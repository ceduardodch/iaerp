"""Pagos al exterior que requieren conciliación antes del 104 y del ATS."""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.payables import Payable, PayableMovement
from app.models.tax import FiscalDocument
from app.services.tax.due_dates import declaration_month
from app.services.tax.formatting import format_amount


async def external_payment_details(
    session: AsyncSession, *, tenant_id: UUID, year: int, month: int
) -> list[str]:
    """Importes efectivamente pagados, agrupados por compra dentro del mes."""
    next_month = declaration_month(year=year, month=month)
    reversal = aliased(PayableMovement)
    rows = await session.execute(
        select(
            Payable.supplier_name,
            Payable.document_number,
            Payable.description,
            Payable.currency,
            func.sum(PayableMovement.amount),
        )
        .select_from(PayableMovement)
        .join(
            Payable,
            (Payable.id == PayableMovement.payable_id)
            & (Payable.tenant_id == PayableMovement.tenant_id),
        )
        .where(
            PayableMovement.tenant_id == tenant_id,
            Payable.foreign_digital_service.is_(True),
            Payable.status != "VOID",
            PayableMovement.movement_type == "PAYMENT",
            ~select(reversal.id)
            .where(
                reversal.tenant_id == tenant_id,
                reversal.reversed_movement_id == PayableMovement.id,
                reversal.movement_type == "REVERSAL",
            )
            .exists(),
            PayableMovement.effective_date >= date(year, month, 1),
            PayableMovement.effective_date < date(*next_month, 1),
        )
        .group_by(
            Payable.id,
            Payable.supplier_name,
            Payable.document_number,
            Payable.description,
            Payable.currency,
        )
        .order_by(Payable.supplier_name, Payable.document_number, Payable.id)
    )
    return [
        f"Servicio digital del exterior · {supplier or 'Proveedor sin nombre'} · "
        f"{number or description} · pago del período {currency} {format_amount(amount)}."
        for supplier, number, description, currency, amount in rows
    ]


def external_review_reasons(payments: list[str], documents: Iterable[FiscalDocument]) -> list[str]:
    reasons = list(payments)
    if payments:
        reasons.append(
            "Revisa la tarifa por servicio, la liquidación y quién recaudó el IVA. "
            "Verifica el casillero 503 cuando corresponda y contrasta el 731 con las "
            "retenciones efectuadas. Concilia el 104 y prepara el ATS fuera de IAERP."
        )
    if any(
        d.doc_type == "LIQUIDACION" and d.direction == "EMITIDO" and d.cancelled_at is None
        for d in documents
    ):
        reasons.append(
            "Hay liquidaciones de compra emitidas por la empresa. Revisa sus bases, "
            "crédito y retenciones en el 104 y el ATS fuera de IAERP."
        )
    return reasons

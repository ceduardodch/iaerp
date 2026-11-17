"""Confirmación humana local de facturas que ya constan ANULADAS en el SRI."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.models.payables import Payable, SupplierPaymentSchedule
from app.models.tax import FiscalDocument, FiscalRetention, TaxEvidence, TaxPeriod
from app.schemas.tax import PurchaseCancellationCreate
from app.services import payables, storage
from app.services.tax import periods
from app.services.tax.ingest import normalize_sri_document_number


async def cancel_purchase(
    session: AsyncSession,
    context: AuthContext,
    *,
    document_id: uuid.UUID,
    data: PurchaseCancellationCreate,
) -> FiscalDocument:
    """Invocar dentro de execute_idempotent; no tiene efectos externos de escritura."""
    if context.actor_type != "USER" or not {"tax:write", "payables:write"} <= context.scopes:
        raise HTTPException(
            403,
            ("La anulación local requiere confirmación humana y permisos de compras y tributario"),
        )
    document = await session.scalar(
        select(FiscalDocument)
        .where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.id == document_id,
        )
        .with_for_update()
    )
    if document is None:
        raise HTTPException(404, "Compra no encontrada")
    if document.direction != "RECIBIDO" or document.doc_type != "FACTURA":
        raise HTTPException(
            422,
            (
                "Sólo se admite la anulación directa de facturas recibidas; las notas "
                "de crédito tienen su propio flujo"
            ),
        )
    if document.cancelled_at is not None:
        raise HTTPException(409, "La compra ya tiene una anulación local registrada")
    if not document.access_key or len(document.access_key) != 49:
        raise HTTPException(
            422,
            ("La factura requiere su clave de acceso SRI exacta antes de registrar la anulación"),
        )
    if not document.issue_date <= data.effective_date <= today_in_fiscal_timezone():
        raise HTTPException(
            422,
            ("La fecha de anulación debe estar entre la emisión y hoy (Ecuador)"),
        )
    # Protege todos los cierres afectados, aunque el documento esté enlazado sólo a IVA.
    affected_dates = {document.issue_date, data.effective_date}
    affected_periods = list(
        await session.scalars(
            select(TaxPeriod)
            .where(
                TaxPeriod.tenant_id == context.tenant_id,
                or_(
                    TaxPeriod.id == document.tax_period_id,
                    *(
                        and_(
                            TaxPeriod.year == day.year,
                            or_(TaxPeriod.month == day.month, TaxPeriod.obligation_type == "RENTA"),
                        )
                        for day in affected_dates
                    ),
                ),
            )
            .order_by(TaxPeriod.id)
            .with_for_update()
        )
    )
    if any(period.status == "DECLARADO" for period in affected_periods):
        raise HTTPException(
            409,
            (
                "La compra afecta un período declarado. Requiere revisión contable y "
                "un ajuste; el cierre y la compra no se modificaron"
            ),
        )
    number = payables._document_number(document)
    related = await session.scalar(
        select(FiscalDocument.id)
        .where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.id != document.id,
            FiscalDocument.doc_type.in_(("NOTA_CREDITO", "RETENCION")),
            FiscalDocument.cancelled_at.is_(None),
            or_(
                FiscalDocument.related_access_key == document.access_key,
                and_(
                    FiscalDocument.related_document_number == number,
                    FiscalDocument.counterparty_identification
                    == document.counterparty_identification,
                )
                if number
                else false(),
            ),
        )
        .limit(1)
    )
    if related is not None:
        raise HTTPException(
            409,
            (
                "La factura tiene una nota de crédito o retención vinculada. Revisa "
                "ese respaldo antes de anular; no se aplicó un segundo descuento"
            ),
        )
    if number:
        support_numbers = await session.scalars(
            select(FiscalRetention.supporting_document_number)
            .join(
                FiscalDocument,
                and_(
                    FiscalDocument.tenant_id == FiscalRetention.tenant_id,
                    FiscalDocument.id == FiscalRetention.fiscal_document_id,
                ),
            )
            .where(
                FiscalRetention.tenant_id == context.tenant_id,
                FiscalDocument.direction == "EMITIDO",
                FiscalDocument.doc_type == "RETENCION",
                FiscalDocument.counterparty_identification == document.counterparty_identification,
            )
        )
        if any(normalize_sri_document_number(value) == number for value in support_numbers):
            raise HTTPException(
                409,
                "La factura tiene una retención emitida respaldada. Requiere revisión contable "
                "de la retención antes de registrar la anulación; no se modificó la compra",
            )
    payable = await session.scalar(
        select(Payable)
        .where(
            Payable.tenant_id == context.tenant_id,
            Payable.fiscal_document_id == document.id,
        )
        .with_for_update()
    )
    if payable is not None:
        movements = await payables._active_movements(
            session, tenant_id=context.tenant_id, payable_id=payable.id
        )
        if movements:
            raise HTTPException(
                409,
                (
                    "La compra tiene pagos, retenciones o notas de crédito aplicados. "
                    "Requiere conciliación contable del pago o saldo a favor; no se "
                    "creó una devolución ni se modificó el historial"
                ),
            )
    evidence = await session.scalar(
        select(TaxEvidence).where(
            TaxEvidence.tenant_id == context.tenant_id, TaxEvidence.id == data.evidence_id
        )
    )
    if evidence is None:
        raise HTTPException(404, "Respaldo de anulación no encontrado")
    if not evidence.object_key.startswith(f"{context.tenant_id}/") or evidence.size_bytes <= 0:
        raise HTTPException(422, "El respaldo no es un archivo privado válido de esta empresa")
    try:
        exists = await storage.object_exists(object_key=evidence.object_key)
    except Exception as error:
        raise HTTPException(
            503, "No se pudo verificar el respaldo guardado. No se modificó la compra"
        ) from error
    if not exists:
        raise HTTPException(
            409,
            ("El archivo de respaldo no está disponible. Vuelve a cargarlo antes de anular"),
        )
    document.cancellation_date = data.effective_date
    document.cancellation_reason = data.reason.strip()
    document.cancellation_evidence_id = evidence.id
    document.cancelled_at = datetime.now(UTC)
    document.cancelled_by_actor_id = context.actor_id
    if payable is not None:
        payable.status = "VOID"
        schedules = await session.scalars(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.tenant_id == context.tenant_id,
                SupplierPaymentSchedule.payable_id == payable.id,
                SupplierPaymentSchedule.status == "SCHEDULED",
            )
        )
        for schedule in schedules:
            schedule.status = "CANCELLED"
    await session.flush()
    if document.tax_period_id is not None:
        await periods.refresh_period_statuses(session, context, period_id=document.tax_period_id)
    return document

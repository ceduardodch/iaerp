"""Expediente de un comprobante: su historia completa en un solo lugar.

Responde la pregunta "que paso con esta factura": que retencion le hicieron, que
cobros entraron (con su referencia bancaria) y cuanto falta. Cruza lo que ya
existe en el sistema, sin duplicar datos:

``FiscalDocument`` (tributario) → ``SalesDocument`` (factura emitida) →
``Receivable`` (cartera) → ``Movement`` (cobros y retenciones aplicadas), mas las
``FiscalRetention`` de los comprobantes de retencion que la respaldan.

Incluye la comprobacion de cobro que pidio el usuario:
``total − retencion IVA − retencion renta = neto esperado``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.receivables import Movement, Receivable
from app.models.tax import FiscalDocument, FiscalRetention
from app.services.tax.formatting import quantize_amount

# Prefijo que usa la conciliacion bancaria al registrar el movimiento
# (``services/bank_reconciliation.py``): "BANCO <referencia> | <transaccion>".
_BANK_PREFIX = "BANCO "


@dataclass
class DossierRetention:
    """Retencion que respalda al comprobante."""

    access_key: str | None
    issue_date: date
    issuer_name: str | None
    iva_amount: Decimal = Decimal("0.00")
    income_tax_amount: Decimal = Decimal("0.00")


@dataclass
class DossierMovement:
    """Movimiento de cartera (cobro, retencion aplicada, nota de credito…)."""

    movement_type: str
    amount: Decimal
    occurred_at: datetime
    reference: str | None = None
    # Referencia bancaria, cuando el cobro vino de la conciliacion del extracto.
    bank_reference: str | None = None


@dataclass
class DocumentDossier:
    document_id: uuid.UUID
    doc_type: str
    direction: str
    access_key: str | None
    issue_date: date
    counterparty_name: str | None
    total: Decimal
    payment_methods: list[str] = field(default_factory=list)
    retentions: list[DossierRetention] = field(default_factory=list)
    movements: list[DossierMovement] = field(default_factory=list)
    # Cartera, solo si el comprobante genero una cuenta por cobrar.
    receivable_id: uuid.UUID | None = None
    receivable_status: str | None = None
    collected_amount: Decimal = Decimal("0.00")
    outstanding_amount: Decimal = Decimal("0.00")
    # total − retencion IVA − retencion renta
    expected_net: Decimal = Decimal("0.00")
    # Lo que falta para llegar al neto esperado (0 si ya cuadra).
    net_difference: Decimal = Decimal("0.00")
    notes: list[str] = field(default_factory=list)

    @property
    def retained_iva(self) -> Decimal:
        return sum((item.iva_amount for item in self.retentions), Decimal("0.00"))

    @property
    def retained_income_tax(self) -> Decimal:
        return sum((item.income_tax_amount for item in self.retentions), Decimal("0.00"))


def _bank_reference(support_reference: str | None) -> str | None:
    if support_reference and support_reference.startswith(_BANK_PREFIX):
        return support_reference[len(_BANK_PREFIX) :]
    return None


async def _retentions_for(
    session: AsyncSession,
    context: AuthContext,
    *,
    document: FiscalDocument,
) -> list[DossierRetention]:
    """Retenciones que respaldan a este comprobante.

    Una retencion apunta a la factura por su numero de documento sustento
    (``001-001-000000045``), no por clave de acceso.
    """
    if document.doc_type == "RETENCION":
        rows = list(
            await session.scalars(
                select(FiscalRetention).where(
                    FiscalRetention.tenant_id == context.tenant_id,
                    FiscalRetention.fiscal_document_id == document.id,
                )
            )
        )
        if not rows:
            return []
        own_retention = DossierRetention(
            access_key=document.access_key,
            issue_date=document.issue_date,
            issuer_name=document.counterparty_name,
        )
        for row in rows:
            if row.kind == "IVA":
                own_retention.iva_amount += row.retained_amount
            else:
                own_retention.income_tax_amount += row.retained_amount
        return [own_retention]

    parts = [
        document.establishment_code,
        document.emission_point_code,
        document.sequential,
    ]
    if not all(parts):
        return []
    supporting_number = "-".join(part for part in parts if part)
    # El SRI tambien acepta el numero sin separadores.
    supporting_plain = "".join(part for part in parts if part)

    rows = list(
        await session.scalars(
            select(FiscalRetention).where(
                FiscalRetention.tenant_id == context.tenant_id,
                FiscalRetention.supporting_document_number.in_(
                    [supporting_number, supporting_plain]
                ),
            )
        )
    )
    if not rows:
        return []

    grouped: dict[uuid.UUID, DossierRetention] = {}
    for row in rows:
        source = await session.get(FiscalDocument, row.fiscal_document_id)
        if source is None or source.tenant_id != context.tenant_id:
            continue
        entry = grouped.get(source.id)
        if entry is None:
            entry = DossierRetention(
                access_key=source.access_key,
                issue_date=source.issue_date,
                issuer_name=source.counterparty_name,
            )
            grouped[source.id] = entry
        if row.kind == "IVA":
            entry.iva_amount += row.retained_amount
        else:
            entry.income_tax_amount += row.retained_amount
    return list(grouped.values())


async def build_dossier(
    session: AsyncSession,
    context: AuthContext,
    *,
    document_id: uuid.UUID,
) -> DocumentDossier:
    """Arma el expediente del comprobante."""
    document = await session.scalar(
        select(FiscalDocument).where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.id == document_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Fiscal document not found")

    dossier = DocumentDossier(
        document_id=document.id,
        doc_type=document.doc_type,
        direction=document.direction,
        access_key=document.access_key,
        issue_date=document.issue_date,
        counterparty_name=document.counterparty_name,
        total=document.total,
        payment_methods=list(document.payment_methods or []),
    )

    dossier.retentions = await _retentions_for(session, context, document=document)

    # Un comprobante propio puede tener cartera; uno recibido no.
    if document.sales_document_id is not None:
        receivable = await session.scalar(
            select(Receivable).where(
                Receivable.tenant_id == context.tenant_id,
                Receivable.sales_document_id == document.sales_document_id,
            )
        )
        if receivable is not None:
            dossier.receivable_id = receivable.id
            dossier.receivable_status = receivable.status

            movements = list(
                await session.scalars(
                    select(Movement)
                    .where(
                        Movement.tenant_id == context.tenant_id,
                        Movement.receivable_id == receivable.id,
                    )
                    .order_by(Movement.created_at)
                )
            )
            applied = Decimal("0.00")
            for movement in movements:
                dossier.movements.append(
                    DossierMovement(
                        movement_type=movement.movement_type,
                        amount=movement.amount,
                        occurred_at=movement.created_at,
                        reference=movement.support_reference,
                        bank_reference=_bank_reference(movement.support_reference),
                    )
                )
                # Un reverso devuelve el valor: no cuenta como cobrado.
                if movement.movement_type != "REVERSAL":
                    applied += movement.amount
                else:
                    applied -= movement.amount

            dossier.collected_amount = quantize_amount(applied)
            dossier.outstanding_amount = quantize_amount(
                receivable.original_amount - applied
            )
    elif document.direction == "EMITIDO":
        dossier.notes.append(
            "Este comprobante todavia no esta enlazado con una factura del sistema: "
            "usa 'Importar mis ventas' para vincularlo con su cartera."
        )

    dossier.expected_net = quantize_amount(
        Decimal("0.00")
        if document.doc_type == "RETENCION"
        else document.total - dossier.retained_iva - dossier.retained_income_tax
    )
    if dossier.receivable_id is not None:
        dossier.net_difference = quantize_amount(
            dossier.expected_net - dossier.collected_amount
        )
        if dossier.net_difference > 0:
            dossier.notes.append(
                "Falta registrar el cobro del neto esperado; una retencion por si sola "
                "no acredita el pago."
            )

    return dossier


__all__ = ["DocumentDossier", "DossierMovement", "DossierRetention", "build_dossier"]

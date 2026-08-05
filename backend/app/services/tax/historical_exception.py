"""Excepción auditada para una venta real cuyo XML original no se recuperó.

No crea ni guarda un comprobante XML. Convierte el RIDE histórico ya validado
en evidencia fiscal solo después de una aprobación humana y de registrar el
respaldo independiente de la forma de pago. El alcance es IVA/ATS; no toca
Cartera, emisión ni transmisión SRI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import DocumentArtifact, SalesDocument, SalesDocumentLine
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.tax import FiscalDocument, FiscalDocumentTax, TaxPeriod


@dataclass(frozen=True)
class HistoricalTaxCandidate:
    id: uuid.UUID
    document_number: str
    access_key: str
    issue_date: date
    customer_name: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    approved: bool


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


async def list_candidates(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
) -> list[HistoricalTaxCandidate]:
    documents = list(
        await session.scalars(
            select(SalesDocument)
            .where(
                SalesDocument.tenant_id == context.tenant_id,
                SalesDocument.status == "HISTORICAL_ISSUED",
                SalesDocument.issue_date >= date(period.year, period.month, 1),
            )
            .order_by(SalesDocument.issue_date, SalesDocument.sequential)
        )
    )
    documents = [
        document
        for document in documents
        if document.issue_date.year == period.year and document.issue_date.month == period.month
    ]
    if not documents:
        return []

    parties = {
        party.id: party
        for party in await session.scalars(
            select(Party).where(
                Party.tenant_id == context.tenant_id,
                Party.id.in_([document.party_id for document in documents]),
            )
        )
    }
    linked_ids = set(
        await session.scalars(
            select(FiscalDocument.sales_document_id).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.sales_document_id.in_([document.id for document in documents]),
            )
        )
    )
    candidates: list[HistoricalTaxCandidate] = []
    for document in documents:
        if not document.access_key:
            continue
        party = parties.get(document.party_id)
        candidates.append(
            HistoricalTaxCandidate(
                id=document.id,
                document_number=document.sequential,
                access_key=document.access_key,
                issue_date=document.issue_date,
                customer_name=party.name if party else "Cliente sin maestro",
                subtotal=document.subtotal,
                tax_total=document.tax_total,
                total=document.total,
                approved=document.id in linked_ids,
            )
        )
    return candidates


async def approve_candidate(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
    sales_document_id: uuid.UUID,
    confirmed: bool,
    evidence_reference: str,
) -> FiscalDocument:
    if not confirmed:
        raise _invalid("Debes confirmar la excepción ATS y el XML original faltante.")
    reference = evidence_reference.strip()
    if len(reference) < 8:
        raise _invalid("Describe el respaldo bancario de la transferencia.")

    document = await session.scalar(
        select(SalesDocument).where(
            SalesDocument.tenant_id == context.tenant_id,
            SalesDocument.id == sales_document_id,
        )
    )
    if document is None or document.status != "HISTORICAL_ISSUED":
        raise HTTPException(status_code=404, detail="Factura histórica no encontrada")
    if document.issue_date.year != period.year or document.issue_date.month != period.month:
        raise _invalid("La factura histórica no pertenece al periodo seleccionado.")
    if not document.access_key or not document.authorization_number or not document.authorized_at:
        raise _invalid("Falta la autorización verificable de la factura histórica.")

    snapshot = dict(document.commercial_snapshot or {})
    if snapshot.get("source") != "RIDE_PDF" or snapshot.get("xml_available") is not False:
        raise _invalid("La excepción solo aplica a un RIDE histórico con XML original faltante.")
    ride = await session.scalar(
        select(DocumentArtifact).where(
            DocumentArtifact.tenant_id == context.tenant_id,
            DocumentArtifact.sales_document_id == document.id,
            DocumentArtifact.artifact_type == "ride-pdf",
        )
    )
    if ride is None or snapshot.get("pdf_sha256") != ride.sha256:
        raise _invalid("El RIDE histórico no tiene un hash verificable.")

    existing = await session.scalar(
        select(FiscalDocument).where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.sales_document_id == document.id,
        )
    )
    if existing is not None:
        return existing

    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == context.tenant_id,
            Party.id == document.party_id,
        )
    )
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.tenant_id == context.tenant_id,
            Establishment.id == document.establishment_id,
        )
    )
    emission_point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.tenant_id == context.tenant_id,
            EmissionPoint.id == document.emission_point_id,
        )
    )
    lines = list(
        await session.scalars(
            select(SalesDocumentLine).where(
                SalesDocumentLine.tenant_id == context.tenant_id,
                SalesDocumentLine.sales_document_id == document.id,
            )
        )
    )
    if party is None or establishment is None or emission_point is None or not lines:
        raise _invalid("El RIDE histórico no tiene todos los maestros o líneas verificadas.")
    if sum((line.base_amount for line in lines), Decimal("0.00")) != document.subtotal:
        raise _invalid("Las bases del RIDE no cuadran con el subtotal histórico.")
    if sum((line.tax_amount for line in lines), Decimal("0.00")) != document.tax_total:
        raise _invalid("El IVA del RIDE no cuadra con el total histórico.")
    if document.subtotal + document.tax_total != document.total:
        raise _invalid("El total histórico no cuadra con base más IVA.")

    fiscal = FiscalDocument(
        tenant_id=context.tenant_id,
        tax_period_id=period.id,
        direction="EMITIDO",
        doc_type="FACTURA",
        access_key=document.access_key,
        authorization_number=document.authorization_number,
        authorized_at=document.authorized_at,
        issue_date=document.issue_date,
        establishment_code=establishment.code,
        emission_point_code=emission_point.code,
        sequential=document.sequential,
        counterparty_identification=party.identification_number,
        counterparty_name=party.name,
        subtotal=document.subtotal,
        tax_total=document.tax_total,
        total=document.total,
        payment_methods=["20"],
        is_preliminary=False,
        sales_document_id=document.id,
    )
    session.add(fiscal)
    await session.flush()
    grouped: dict[tuple[str, Decimal], tuple[Decimal, Decimal]] = {}
    for line in lines:
        key = (line.tax_sri_code, line.tax_rate)
        base, tax = grouped.get(key, (Decimal("0.00"), Decimal("0.00")))
        grouped[key] = (base + line.base_amount, tax + line.tax_amount)
    for (sri_code, rate), (base, tax) in grouped.items():
        session.add(
            FiscalDocumentTax(
                tenant_id=context.tenant_id,
                fiscal_document_id=fiscal.id,
                sri_tax_code=sri_code,
                tax_bracket="GRAVADO" if rate > 0 else "TARIFA_CERO",
                rate=rate,
                base_amount=base,
                tax_amount=tax,
            )
        )

    snapshot["tax_exception"] = {
        "scope": "IVA_ATS_ONLY",
        "xml_original_missing": True,
        "payment_method": "20",
        "evidence_source": "BANK_STATEMENT",
        "evidence_reference": reference,
        "approved_by": context.actor_id,
        "approved_at": datetime.now(UTC).isoformat(),
    }
    document.commercial_snapshot = snapshot
    await session.flush()
    return fiscal


__all__ = ["HistoricalTaxCandidate", "approve_candidate", "list_candidates"]

"""Apply authorized tax withholdings to their exact customer invoice.

Fiscal custody must succeed even when a commercial application needs review.
No cash is inferred, and an existing manual settlement is never rewritten.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.platform import Tenant
from app.models.receivables import Movement, Receivable
from app.models.tax import FiscalDocument, TaxEvidence
from app.schemas.receivables import PaymentInput
from app.services import receivables, storage
from app.services.tax.identification import receiver_matches_tenant
from app.services.tax.sri_xml import ParsedDocument, ParsedRetention, parse_authorized_document
from app.services.unit_of_work import append_audit


@dataclass
class RetentionSyncResult:
    applied: int = 0
    omitted: int = 0
    pending: int = 0
    notes: list[str] = field(default_factory=list)

    def review(self, code: str) -> None:
        self.pending += 1
        if code not in self.notes:
            self.notes.append(code)


def _support(value: str | None) -> str | None:
    # Do not accept arbitrary text or partial invoice numbers.
    compact = (value or "").replace("-", "")
    return compact if len(compact) == 15 and compact.isdigit() else None


async def _apply_parsed(
    session: AsyncSession,
    context: AuthContext,
    *,
    parsed: ParsedDocument,
    fiscal_document_id: uuid.UUID,
    correlation_id: str,
    target_receivable_id: uuid.UUID | None = None,
) -> RetentionSyncResult:
    result = RetentionSyncResult()
    tenant = await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if (
        parsed.doc_type != "RETENCION"
        or tenant is None
        or parsed.issuer_identification == tenant.ruc
    ):
        return result
    if not receiver_matches_tenant(parsed.receiver_identification, tenant.ruc):
        result.review("RETENTION_SUBJECT_MISMATCH")
        return result
    if (
        not parsed.authorization_number.isdigit()
        or len(parsed.authorization_number) != 49
        or parsed.access_key != parsed.authorization_number
    ):
        result.review("RETENTION_AUTHORIZATION_INVALID")
        return result
    groups: dict[str, list[ParsedRetention]] = defaultdict(list)
    for item in parsed.retentions:
        number = _support(item.supporting_document_number)
        if number is None:
            result.review("RETENTION_SUPPORT_INVALID")
            continue
        groups[number].append(item)
    for number, items in sorted(groups.items()):
        if any(item.supporting_document_type != "01" for item in items):
            result.review("RETENTION_SUPPORT_TYPE_REVIEW_REQUIRED")
            continue
        statement = (
            select(Receivable)
            .join(
                SalesDocument,
                (SalesDocument.tenant_id == Receivable.tenant_id)
                & (SalesDocument.id == Receivable.sales_document_id),
            )
            .join(
                Party, (Party.tenant_id == Receivable.tenant_id) & (Party.id == Receivable.party_id)
            )
            .join(
                Establishment,
                (Establishment.tenant_id == SalesDocument.tenant_id)
                & (Establishment.id == SalesDocument.establishment_id),
            )
            .join(
                EmissionPoint,
                (EmissionPoint.tenant_id == SalesDocument.tenant_id)
                & (EmissionPoint.id == SalesDocument.emission_point_id),
            )
            .where(
                Receivable.tenant_id == context.tenant_id,
                SalesDocument.document_type == "INVOICE",
                SalesDocument.status == "AUTHORIZED",
                SalesDocument.party_id == Receivable.party_id,
                Party.identification_number == parsed.issuer_identification,
                Establishment.code == number[:3],
                EmissionPoint.code == number[3:6],
                SalesDocument.sequential == number[6:],
            )
            .limit(2)
        )
        matches = list(await session.scalars(statement))
        if target_receivable_id is not None:
            if not any(match.id == target_receivable_id for match in matches):
                continue
        if len(matches) != 1:
            result.review("RETENTION_INVOICE_UNRESOLVED")
            continue
        match = matches[0]
        if any(
            not item.retained_amount.is_finite() or item.retained_amount <= 0 or not item.sri_code
            for item in items
        ):
            result.review("RETENTION_AMOUNT_INVALID")
            continue
        # Repeated same-code lines have one commercial reference; preserve their
        # exact sum rather than violating the per-installment reference constraint.
        grouped_items: dict[tuple[str, str], ParsedRetention] = {}
        for item in items:
            key = (item.kind, item.sri_code)
            if key not in grouped_items:
                grouped_items[key] = ParsedRetention(
                    kind=item.kind,
                    sri_code=item.sri_code,
                    percentage=item.percentage,
                    base_amount=item.base_amount,
                    retained_amount=item.retained_amount,
                    supporting_document_number=number,
                    supporting_document_type="01",
                )
            else:
                grouped_items[key].retained_amount += item.retained_amount
        items = list(grouped_items.values())
        expected = sorted((f"RETENTION_{item.kind}", item.retained_amount) for item in items)
        # All paths acquire the same lock BEFORE testing authorization duplicates.
        # Savepoint isolates commercial failures from the tax document transaction.
        try:
            async with session.begin_nested():
                locked = await receivables.lock_receivable(
                    session, tenant_id=context.tenant_id, receivable_id=match.id
                )
                if locked.status in {"VOID", "VOIDED"}:
                    result.review("RETENTION_INVOICE_VOIDED")
                    continue
                existing = await receivables._active_retention_movements(
                    session,
                    tenant_id=context.tenant_id,
                    receivable_id=match.id,
                    authorization_number=parsed.authorization_number,
                )
                if existing:
                    signatures = [
                        receivables._retention_movement_signature(row) for row in existing
                    ]
                    actual = sorted(signature for signature in signatures if signature is not None)
                    if actual != expected or len(actual) != len(existing):
                        result.review("RETENTION_EXISTING_CONFLICT")
                    else:
                        result.omitted += 1
                    continue
                historical = await session.scalar(
                    select(Movement.id)
                    .where(
                        Movement.tenant_id == context.tenant_id,
                        Movement.receivable_id == match.id,
                        Movement.movement_type == "RETENTION",
                        Movement.support_reference.like(f"{parsed.authorization_number} |%"),
                    )
                    .limit(1)
                )
                if historical is not None:
                    result.review("RETENTION_REVERSED_REVIEW_REQUIRED")
                    continue
                await receivables.record_payment(
                    session,
                    context,
                    match.id,
                    PaymentInput(
                        cash_amount=Decimal("0.00"),
                        payment_date=parsed.issue_date,
                        retentions=[
                            {
                                "kind": f"RETENTION_{item.kind}",
                                "amount": item.retained_amount,
                                "reason": f"Código SRI {item.sri_code}",
                                "document_reference": parsed.authorization_number,
                            }
                            for item in items
                        ],
                    ),
                    correlation_id=correlation_id,
                    idempotency_key=f"tax-retention:{parsed.access_key}:{number}",
                    skip_fiscal_retention_sync=True,
                )
                await append_audit(
                    session,
                    context=context,
                    action="retention.tax_applied",
                    entity_type="receivable",
                    entity_id=str(match.id),
                    correlation_id=correlation_id,
                    idempotency_key=f"tax-retention:{parsed.access_key}:{number}",
                    details={
                        "fiscal_document_id": str(fiscal_document_id),
                        "retention_count": len(items),
                    },
                )
                await session.flush()
                result.applied += 1
        except (HTTPException, IntegrityError):
            result.review("RETENTION_BALANCE_REVIEW_REQUIRED")
    return result


async def sync_ingested_retention(
    session: AsyncSession,
    context: AuthContext,
    *,
    document: FiscalDocument,
    parsed: ParsedDocument,
) -> RetentionSyncResult:
    # REST and the recovery worker already acquire this before fiscal writes.
    # Keep the same order for reconciliation across several customer invoices.
    await session.scalar(
        select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
    )
    return await _apply_parsed(
        session,
        context,
        parsed=parsed,
        fiscal_document_id=document.id,
        correlation_id=f"tax-retention:{document.id}",
    )


async def sync_receivable_retentions(
    session: AsyncSession,
    context: AuthContext,
    receivable_id: uuid.UUID,
    *,
    correlation_id: str,
    idempotency_key: str,
) -> RetentionSyncResult:
    """Reconcile older records on an explicit payment preparation/write, not GET."""
    await session.scalar(
        select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
    )
    match = await receivables.lock_receivable(
        session, tenant_id=context.tenant_id, receivable_id=receivable_id
    )
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == context.tenant_id,
            Party.id == match.party_id,
        )
    )
    if party is None:
        return RetentionSyncResult()
    return await _sync_stored_retentions(
        session,
        context,
        correlation_id=correlation_id,
        target_receivable_id=receivable_id,
        issuer=party.identification_number,
    )


async def sync_tenant_retentions(
    session: AsyncSession,
    context: AuthContext,
    *,
    correlation_id: str,
    idempotency_key: str,
) -> RetentionSyncResult:
    """Explicit audited tenant-wide reconciliation for already imported XML."""
    await session.scalar(
        select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
    )
    return await _sync_stored_retentions(session, context, correlation_id=correlation_id)


async def _sync_stored_retentions(
    session: AsyncSession,
    context: AuthContext,
    *,
    correlation_id: str,
    target_receivable_id: uuid.UUID | None = None,
    issuer: str | None = None,
) -> RetentionSyncResult:
    result = RetentionSyncResult()
    statement = (
        select(FiscalDocument)
        .where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.direction == "RECIBIDO",
            FiscalDocument.doc_type == "RETENCION",
            FiscalDocument.is_preliminary.is_(False),
        )
        .order_by(FiscalDocument.issue_date, FiscalDocument.id)
    )
    if issuer is not None:
        statement = statement.where(FiscalDocument.counterparty_identification == issuer)
    documents = list(await session.scalars(statement))
    cache: dict[uuid.UUID, list[ParsedDocument]] = {}
    for document in documents:
        evidence = await session.scalar(
            select(TaxEvidence).where(
                TaxEvidence.tenant_id == context.tenant_id,
                TaxEvidence.id == document.evidence_id,
            )
        )
        if evidence is None or evidence.file_type not in {"XML", "ZIP"}:
            result.review("RETENTION_XML_REQUIRED")
            continue
        try:
            if evidence.id not in cache:
                data = await storage.download_artifact(object_key=evidence.object_key)
                if hashlib.sha256(data).hexdigest() != evidence.sha256:
                    raise ValueError("Evidence hash mismatch")
                from app.services.tax.ingest import extract_xml_members

                payloads = (
                    [content for _, content in extract_xml_members(data)]
                    if evidence.file_type == "ZIP"
                    else [data]
                )
                cache[evidence.id] = [parse_authorized_document(payload) for payload in payloads]
            candidates = [
                parsed
                for parsed in cache[evidence.id]
                if parsed.access_key == document.access_key
                and parsed.authorization_number == document.authorization_number
            ]
            if len(candidates) != 1:
                raise ValueError("Evidence document mismatch")
        except Exception:
            # Storage failure or bad legacy evidence must not infer a settlement.
            result.review("RETENTION_XML_UNAVAILABLE")
            continue
        child = await _apply_parsed(
            session,
            context,
            parsed=candidates[0],
            fiscal_document_id=document.id,
            correlation_id=correlation_id,
            target_receivable_id=target_receivable_id,
        )
        result.applied += child.applied
        result.omitted += child.omitted
        result.pending += child.pending
        result.notes.extend(code for code in child.notes if code not in result.notes)
    return result

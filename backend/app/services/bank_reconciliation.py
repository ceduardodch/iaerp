from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.receivables import Movement, Receivable
from app.schemas.bank_reconciliation import (
    BankStatementImportRead,
    BankStatementManualCorrectionRead,
    BankStatementMatchRead,
)
from app.schemas.receivables import PaymentInput
from app.services import receivables

MAX_BANK_STATEMENT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class BankCredit:
    occurred_at: datetime
    reference: str
    description: str
    amount: Decimal
    transaction_id: str


@dataclass(frozen=True)
class ParsedBankStatement:
    source_sha256: str
    total_rows: int
    debit_rows: int
    credits: list[BankCredit]


@dataclass(frozen=True)
class ReceivableCandidate:
    receivable: Receivable
    document: SalesDocument
    open_amount: Decimal
    retention_total: Decimal
    manual_payment: Movement | None


@dataclass(frozen=True)
class ManualCorrectionCandidate:
    credit: BankCredit
    target_receivable: Receivable
    target_document: SalesDocument
    manual_receivable: Receivable
    manual_document: SalesDocument
    manual_payment: Movement


def parse_bank_statement(content: bytes) -> ParsedBankStatement:
    if not content or len(content) > MAX_BANK_STATEMENT_BYTES:
        raise HTTPException(
            status_code=422,
            detail="Bank statement must be between 1 byte and 2 MB",
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Bank statement must use UTF-8") from exc
    if "\x00" in text:
        raise HTTPException(status_code=422, detail="Bank statement contains invalid data")

    account_number = ""
    has_header = False
    credits: list[BankCredit] = []
    debit_rows = 0
    total_rows = 0
    seen_transactions: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("CUENTA:"):
            account_number = "".join(character for character in line if character.isdigit())
        if line.startswith("FECHA REFERENCIA DESCRIPCION"):
            has_header = True
            continue
        columns = raw_line.rstrip().split("\t")
        if len(columns) < 8 or columns[3].strip() not in {"+", "-"}:
            continue
        if not has_header or not account_number:
            raise HTTPException(status_code=422, detail="Unsupported bank statement structure")
        try:
            occurred_at = datetime.strptime(columns[0].strip(), "%m/%d/%Y %H:%M:%S.%f")
            amount = Decimal(columns[4].strip()).quantize(Decimal("0.01"))
        except (ValueError, InvalidOperation) as exc:
            raise HTTPException(
                status_code=422, detail="Bank statement has an invalid row"
            ) from exc
        if not amount.is_finite() or amount <= 0:
            raise HTTPException(status_code=422, detail="Bank statement has an invalid amount")
        reference = columns[1].strip()
        description = columns[2].strip()
        if not reference or not description:
            raise HTTPException(status_code=422, detail="Bank statement row lacks reference")

        total_rows += 1
        if columns[3].strip() == "-":
            debit_rows += 1
            continue
        fingerprint_input = "|".join(
            (
                account_number,
                occurred_at.isoformat(timespec="milliseconds"),
                reference,
                description,
                f"{amount:.2f}",
            )
        )
        transaction_id = hashlib.sha256(fingerprint_input.encode()).hexdigest()
        if transaction_id in seen_transactions:
            continue
        seen_transactions.add(transaction_id)
        credits.append(
            BankCredit(
                occurred_at=occurred_at,
                reference=reference[:120],
                description=description[:300],
                amount=amount,
                transaction_id=transaction_id,
            )
        )
    if not has_header or total_rows == 0:
        raise HTTPException(status_code=422, detail="Unsupported or empty bank statement")
    return ParsedBankStatement(
        source_sha256=hashlib.sha256(content).hexdigest(),
        total_rows=total_rows,
        debit_rows=debit_rows,
        credits=credits,
    )


def _bank_reference(credit: BankCredit) -> str:
    return f"BANCO {credit.reference[:100]} | {credit.transaction_id}"


async def _receivable_candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: date
) -> list[ReceivableCandidate]:
    entities = list(
        await session.scalars(
            select(Receivable).where(
                Receivable.tenant_id == tenant_id,
                Receivable.status.in_(("OPEN", "PARTIALLY_PAID", "PAID")),
            )
        )
    )
    candidates: list[ReceivableCandidate] = []
    for entity in entities:
        document = await session.scalar(
            select(SalesDocument).where(
                SalesDocument.tenant_id == tenant_id,
                SalesDocument.id == entity.sales_document_id,
                SalesDocument.document_type == "INVOICE",
                SalesDocument.status == "AUTHORIZED",
                SalesDocument.issue_date >= period,
            )
        )
        if (
            document is None
            or document.issue_date.year != period.year
            or document.issue_date.month != period.month
        ):
            continue
        active_movements = list(
            await session.scalars(
                select(Movement).where(
                    Movement.tenant_id == tenant_id,
                    Movement.receivable_id == entity.id,
                    Movement.reversed_movement_id.is_(None),
                    Movement.id.not_in(receivables._reversed_movement_ids(tenant_id)),
                )
            )
        )
        if any(
            movement.movement_type not in {"RETENTION", "PAYMENT"} for movement in active_movements
        ):
            continue
        retention_movements = [
            movement for movement in active_movements if movement.movement_type == "RETENTION"
        ]
        payment_movements = [
            movement for movement in active_movements if movement.movement_type == "PAYMENT"
        ]
        if len(payment_movements) > 1:
            continue
        retention_total = sum(
            (movement.amount for movement in retention_movements), Decimal("0.00")
        )
        expected_cash = entity.original_amount - retention_total
        if expected_cash <= 0:
            continue
        manual_payment: Movement | None = None
        if payment_movements:
            manual_payment = payment_movements[0]
            if (
                manual_payment.support_reference or ""
            ).strip() or manual_payment.amount != expected_cash:
                continue
        else:
            open_amount = await receivables.compute_receivable_balance(
                session, tenant_id=tenant_id, receivable=entity
            )
            if open_amount != expected_cash:
                continue
        candidates.append(
            ReceivableCandidate(
                receivable=entity,
                document=document,
                open_amount=expected_cash,
                retention_total=retention_total,
                manual_payment=manual_payment,
            )
        )
    return candidates


async def _active_movements(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> list[Movement]:
    return list(
        await session.scalars(
            select(Movement).where(
                Movement.tenant_id == tenant_id,
                Movement.receivable_id == receivable_id,
                Movement.reversed_movement_id.is_(None),
                Movement.id.not_in(receivables._reversed_movement_ids(tenant_id)),
            )
        )
    )


async def _manual_correction_candidate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    period: date,
    credit: BankCredit,
    target_receivable: Receivable,
    target_document: SalesDocument,
) -> ManualCorrectionCandidate | None:
    if (
        target_document.issue_date.year != period.year
        or target_document.issue_date.month != period.month
    ):
        return None
    target_movements = await _active_movements(
        session, tenant_id=tenant_id, receivable_id=target_receivable.id
    )
    if any(
        movement.movement_type not in {"PAYMENT", "RETENTION"}
        for movement in target_movements
    ):
        return None
    target_applied = sum(
        (movement.amount for movement in target_movements), Decimal("0.00")
    )
    bank_reference = _bank_reference(credit)
    has_bank_payment = any(
        movement.movement_type == "PAYMENT"
        and movement.support_reference == bank_reference
        for movement in target_movements
    )
    has_replaceable_target_payment = any(
        movement.movement_type == "PAYMENT"
        and not (movement.support_reference or "").strip()
        and movement.amount == credit.amount
        for movement in target_movements
    )
    target_is_supported = (
        has_bank_payment and target_applied == target_receivable.original_amount
    ) or (
        not has_bank_payment
        and (
            target_applied + credit.amount == target_receivable.original_amount
            or (
                has_replaceable_target_payment
                and target_applied == target_receivable.original_amount
            )
        )
    )
    if not target_is_supported:
        return None

    siblings = list(
        await session.scalars(
            select(Receivable).where(
                Receivable.tenant_id == tenant_id,
                Receivable.party_id == target_receivable.party_id,
                Receivable.id != target_receivable.id,
                Receivable.status.in_(("OPEN", "PARTIALLY_PAID", "PAID")),
            )
        )
    )
    corrections: list[ManualCorrectionCandidate] = []
    for sibling in siblings:
        document = await session.scalar(
            select(SalesDocument).where(
                SalesDocument.tenant_id == tenant_id,
                SalesDocument.id == sibling.sales_document_id,
                SalesDocument.document_type == "INVOICE",
                SalesDocument.status == "AUTHORIZED",
            )
        )
        if (
            document is None
            or document.issue_date.year != period.year
            or document.issue_date.month != period.month
            or document.issue_date <= credit.occurred_at.date()
        ):
            continue
        movements = await _active_movements(
            session, tenant_id=tenant_id, receivable_id=sibling.id
        )
        if len(movements) != 1:
            continue
        manual_payment = movements[0]
        if (
            manual_payment.movement_type != "PAYMENT"
            or (manual_payment.support_reference or "").strip()
            or manual_payment.amount != credit.amount
        ):
            continue
        corrections.append(
            ManualCorrectionCandidate(
                credit=credit,
                target_receivable=target_receivable,
                target_document=target_document,
                manual_receivable=sibling,
                manual_document=document,
                manual_payment=manual_payment,
            )
        )
    if len(corrections) != 1:
        return None
    return corrections[0]


async def import_bank_statement(
    session: AsyncSession,
    *,
    context: AuthContext,
    file_name: str,
    content: bytes,
    period: date,
    apply: bool,
    correlation_id: str,
    idempotency_key: str,
) -> BankStatementImportRead:
    parsed = parse_bank_statement(content)
    period_credits = [
        credit
        for credit in parsed.credits
        if credit.occurred_at.year == period.year and credit.occurred_at.month == period.month
    ]
    imported_payments = list(
        await session.scalars(
            select(Movement).where(
                Movement.tenant_id == context.tenant_id,
                Movement.movement_type == "PAYMENT",
                Movement.support_reference.in_(
                    [_bank_reference(credit) for credit in period_credits]
                ),
            )
        )
    )
    imported_by_reference = {
        movement.support_reference: movement
        for movement in imported_payments
        if movement.support_reference is not None
    }
    imported_references = set(imported_by_reference)
    pending_credits = [
        credit for credit in period_credits if _bank_reference(credit) not in imported_references
    ]
    candidates = await _receivable_candidates(session, tenant_id=context.tenant_id, period=period)

    credits_by_amount: dict[Decimal, list[BankCredit]] = defaultdict(list)
    candidates_by_amount: dict[Decimal, list[ReceivableCandidate]] = defaultdict(list)
    for credit in pending_credits:
        credits_by_amount[credit.amount].append(credit)
    for candidate in candidates:
        candidates_by_amount[candidate.open_amount].append(candidate)

    matches: list[BankStatementMatchRead] = []
    for amount, amount_credits in credits_by_amount.items():
        amount_candidates = [
            candidate
            for candidate in candidates_by_amount.get(amount, [])
            if candidate.document.issue_date <= amount_credits[0].occurred_at.date()
        ]
        if len(amount_credits) != 1 or len(amount_candidates) != 1:
            continue
        credit = amount_credits[0]
        candidate = amount_candidates[0]
        if credit.occurred_at.date() < candidate.document.issue_date:
            continue
        status = "MATCHED"
        detail = (
            "Reemplazará cobro manual con respaldo bancario"
            if candidate.manual_payment is not None
            else "Lista para registrar"
        )
        if apply:
            if candidate.manual_payment is not None:
                await receivables.reverse_movement(
                    session,
                    context,
                    receivable_id=candidate.receivable.id,
                    movement_id=candidate.manual_payment.id,
                    reason=(
                        "Sustituido por evidencia bancaria "
                        f"{credit.reference} del {credit.occurred_at.date().isoformat()}"
                    ),
                    correlation_id=correlation_id,
                    idempotency_key=f"{idempotency_key}:reverse:{credit.transaction_id}",
                )
            await receivables.record_payment(
                session,
                context,
                candidate.receivable.id,
                PaymentInput(
                    cash_amount=credit.amount,
                    payment_date=credit.occurred_at.date(),
                    method="TRANSFER",
                    reference=_bank_reference(credit),
                ),
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:{credit.transaction_id}",
            )
            status = "REGISTERED"
            detail = (
                "Cobro manual reemplazado con respaldo bancario"
                if candidate.manual_payment is not None
                else "Cobro registrado"
            )
        matches.append(
            BankStatementMatchRead(
                transaction_id=credit.transaction_id,
                payment_date=credit.occurred_at.date(),
                reference=credit.reference,
                description=credit.description,
                amount=credit.amount,
                receivable_id=candidate.receivable.id,
                invoice_sequential=candidate.document.sequential,
                original_amount=candidate.receivable.original_amount,
                retention_total=candidate.retention_total,
                replaces_manual_payment=candidate.manual_payment is not None,
                status=status,
                detail=detail,
            )
        )

    targets_by_transaction: dict[str, tuple[Receivable, SalesDocument]] = {}
    for match in matches:
        candidate = next(
            item for item in candidates if item.receivable.id == match.receivable_id
        )
        targets_by_transaction[match.transaction_id] = (
            candidate.receivable,
            candidate.document,
        )
    for credit in period_credits:
        imported = imported_by_reference.get(_bank_reference(credit))
        if imported is None:
            continue
        target_receivable = await session.scalar(
            select(Receivable).where(
                Receivable.tenant_id == context.tenant_id,
                Receivable.id == imported.receivable_id,
            )
        )
        if target_receivable is None:
            continue
        target_document = await session.scalar(
            select(SalesDocument).where(
                SalesDocument.tenant_id == context.tenant_id,
                SalesDocument.id == target_receivable.sales_document_id,
            )
        )
        if target_document is not None:
            targets_by_transaction[credit.transaction_id] = (
                target_receivable,
                target_document,
            )

    manual_corrections: list[BankStatementManualCorrectionRead] = []
    for credit in period_credits:
        target = targets_by_transaction.get(credit.transaction_id)
        if target is None:
            continue
        correction = await _manual_correction_candidate(
            session,
            tenant_id=context.tenant_id,
            period=period,
            credit=credit,
            target_receivable=target[0],
            target_document=target[1],
        )
        if correction is None:
            continue
        status = "CORRECTION_REQUIRED"
        detail = (
            f"El abono bancario corresponde a {correction.target_document.sequential}; "
            f"el cobro manual de {correction.manual_document.sequential} es posterior "
            "al abono y se conservará mediante un reverso"
        )
        if apply:
            await receivables.reverse_movement(
                session,
                context,
                receivable_id=correction.manual_receivable.id,
                movement_id=correction.manual_payment.id,
                reason=(
                    "Corregido por evidencia bancaria "
                    f"{credit.reference} del {credit.occurred_at.date().isoformat()}; "
                    f"comprobante destino {correction.target_document.sequential}"
                ),
                correlation_id=correlation_id,
                idempotency_key=f"{idempotency_key}:manual-correction:{credit.transaction_id}",
            )
            status = "CORRECTED"
            detail = (
                f"Cobro manual de {correction.manual_document.sequential} revertido; "
                f"el original sigue en auditoría y el banco queda en "
                f"{correction.target_document.sequential}"
            )
        manual_corrections.append(
            BankStatementManualCorrectionRead(
                transaction_id=credit.transaction_id,
                payment_date=credit.occurred_at.date(),
                reference=credit.reference,
                amount=credit.amount,
                target_receivable_id=correction.target_receivable.id,
                target_invoice_sequential=correction.target_document.sequential,
                manual_receivable_id=correction.manual_receivable.id,
                manual_invoice_sequential=correction.manual_document.sequential,
                manual_movement_id=correction.manual_payment.id,
                status=status,
                detail=detail,
            )
        )
    already_imported_count = len(period_credits) - len(pending_credits)
    return BankStatementImportRead(
        period=period.strftime("%Y-%m"),
        file_name=file_name,
        source_sha256=parsed.source_sha256,
        total_rows=parsed.total_rows,
        credit_rows=len(period_credits),
        outside_period_credit_count=len(parsed.credits) - len(period_credits),
        matched_count=len(matches),
        unmatched_credit_count=len(pending_credits) - len(matches),
        ignored_debit_count=parsed.debit_rows,
        already_imported_count=already_imported_count,
        manual_correction_count=len(manual_corrections),
        matches=matches,
        manual_corrections=manual_corrections,
    )

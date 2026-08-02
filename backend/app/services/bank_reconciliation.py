from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.receivables import Movement, Receivable
from app.schemas.bank_reconciliation import BankStatementImportRead, BankStatementMatchRead
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
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[ReceivableCandidate]:
    entities = list(
        await session.scalars(
            select(Receivable).where(
                Receivable.tenant_id == tenant_id,
                Receivable.status.in_(("OPEN", "PARTIALLY_PAID")),
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
            )
        )
        if document is None:
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
        if any(movement.movement_type != "RETENTION" for movement in active_movements):
            continue
        open_amount = await receivables.compute_receivable_balance(
            session, tenant_id=tenant_id, receivable=entity
        )
        if open_amount <= 0:
            continue
        retention_total = sum(
            (movement.amount for movement in active_movements), Decimal("0.00")
        )
        candidates.append(
            ReceivableCandidate(
                receivable=entity,
                document=document,
                open_amount=open_amount,
                retention_total=retention_total,
            )
        )
    return candidates


async def import_bank_statement(
    session: AsyncSession,
    *,
    context: AuthContext,
    file_name: str,
    content: bytes,
    apply: bool,
    correlation_id: str,
    idempotency_key: str,
) -> BankStatementImportRead:
    parsed = parse_bank_statement(content)
    imported_references = set(
        await session.scalars(
            select(Movement.support_reference).where(
                Movement.tenant_id == context.tenant_id,
                Movement.movement_type == "PAYMENT",
                Movement.support_reference.in_(
                    [_bank_reference(credit) for credit in parsed.credits]
                ),
            )
        )
    )
    pending_credits = [
        credit for credit in parsed.credits if _bank_reference(credit) not in imported_references
    ]
    candidates = await _receivable_candidates(session, tenant_id=context.tenant_id)

    credits_by_amount: dict[Decimal, list[BankCredit]] = defaultdict(list)
    candidates_by_amount: dict[Decimal, list[ReceivableCandidate]] = defaultdict(list)
    for credit in pending_credits:
        credits_by_amount[credit.amount].append(credit)
    for candidate in candidates:
        candidates_by_amount[candidate.open_amount].append(candidate)

    matches: list[BankStatementMatchRead] = []
    for amount, amount_credits in credits_by_amount.items():
        amount_candidates = candidates_by_amount.get(amount, [])
        if len(amount_credits) != 1 or len(amount_candidates) != 1:
            continue
        credit = amount_credits[0]
        candidate = amount_candidates[0]
        if credit.occurred_at.date() < candidate.document.issue_date:
            continue
        status = "MATCHED"
        detail = "Lista para registrar"
        if apply:
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
            detail = "Cobro registrado"
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
                status=status,
                detail=detail,
            )
        )
    already_imported_count = len(parsed.credits) - len(pending_credits)
    return BankStatementImportRead(
        file_name=file_name,
        source_sha256=parsed.source_sha256,
        total_rows=parsed.total_rows,
        credit_rows=len(parsed.credits),
        matched_count=len(matches),
        unmatched_credit_count=len(pending_credits) - len(matches),
        ignored_debit_count=parsed.debit_rows,
        already_imported_count=already_imported_count,
        matches=matches,
    )

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
from app.core.timezones import FISCAL_TIMEZONE
from app.models.billing import SalesDocument
from app.models.payables import (
    BankStatementImport,
    BankTransactionAllocation,
    Payable,
    PayableMovement,
)
from app.models.payables import BankTransaction as StoredBankTransaction
from app.models.receivables import Movement, Receivable
from app.schemas.bank_reconciliation import (
    BankStatementDebitMatchRead,
    BankStatementDebitSuggestionRead,
    BankStatementImportRead,
    BankStatementManualCorrectionRead,
    BankStatementMatchRead,
)
from app.schemas.payables import BankDebitAllocationInput, PayablePaymentCreate
from app.schemas.receivables import PaymentInput
from app.services import payables, receivables

MAX_BANK_STATEMENT_BYTES = 2 * 1024 * 1024


def _child_idempotency_key(
    parent_key: str, *, operation: str, transaction_id: str
) -> str:
    """Derive a stable audit key that always fits the database column."""
    digest = hashlib.sha256(
        f"{parent_key}|{operation}|{transaction_id}".encode()
    ).hexdigest()
    return f"bank:{operation}:{digest}"


@dataclass(frozen=True)
class BankTransaction:
    occurred_at: datetime
    reference: str
    description: str
    amount: Decimal
    transaction_id: str
    direction: str


@dataclass(frozen=True)
class ParsedBankStatement:
    source_sha256: str
    account_masked: str
    account_last4: str
    total_rows: int
    transactions: list[BankTransaction]

    @property
    def credits(self) -> list[BankTransaction]:
        return [item for item in self.transactions if item.direction == "CREDIT"]

    @property
    def debits(self) -> list[BankTransaction]:
        return [item for item in self.transactions if item.direction == "DEBIT"]

    @property
    def debit_rows(self) -> int:
        return len(self.debits)


@dataclass(frozen=True)
class ReceivableCandidate:
    receivable: Receivable
    document: SalesDocument
    open_amount: Decimal
    retention_total: Decimal
    manual_payment: Movement | None


@dataclass(frozen=True)
class ManualCorrectionCandidate:
    credit: BankTransaction
    target_receivable: Receivable
    target_document: SalesDocument
    manual_receivable: Receivable
    manual_document: SalesDocument
    manual_payment: Movement


@dataclass(frozen=True)
class PayableBankCandidate:
    payable: Payable
    match_amount: Decimal
    existing_payment: PayableMovement | None


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
    transactions: list[BankTransaction] = []
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
        direction = "CREDIT" if columns[3].strip() == "+" else "DEBIT"
        fingerprint_input = "|".join(
            (
                account_number,
                direction,
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
        transactions.append(
            BankTransaction(
                occurred_at=occurred_at.replace(tzinfo=FISCAL_TIMEZONE),
                reference=reference[:120],
                description=description[:300],
                amount=amount,
                transaction_id=transaction_id,
                direction=direction,
            )
        )
    if not has_header or total_rows == 0:
        raise HTTPException(status_code=422, detail="Unsupported or empty bank statement")
    return ParsedBankStatement(
        source_sha256=hashlib.sha256(content).hexdigest(),
        account_masked=f"****{account_number[-4:]}",
        account_last4=account_number[-4:],
        total_rows=total_rows,
        transactions=transactions,
    )


def _bank_reference(credit: BankTransaction) -> str:
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
    credit: BankTransaction,
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


def _debit_classification(description: str) -> str:
    normalized = description.casefold()
    if any(value in normalized for value in ("tarifa", "comision", "comisión")):
        return "BANK_FEE"
    if any(value in normalized for value in ("impuesto", "isf")):
        return "BANK_TAX"
    if any(value in normalized for value in ("pago tarjeta", "visa", "mastercard", "diners")):
        return "CARD_SETTLEMENT"
    if any(value in normalized for value in ("transferencia entre cuentas", "transfer interna")):
        return "INTERNAL_TRANSFER"
    return "UNCLASSIFIED"


async def _payable_candidates(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    period: date,
) -> list[PayableBankCandidate]:
    entities = list(
        await session.scalars(
            select(Payable).where(
                Payable.tenant_id == tenant_id,
                Payable.status.in_(("OPEN", "PARTIALLY_PAID", "PAID")),
                Payable.issue_date < date(
                    period.year + (1 if period.month == 12 else 0),
                    1 if period.month == 12 else period.month + 1,
                    1,
                ),
            )
        )
    )
    candidates: list[PayableBankCandidate] = []
    for payable in entities:
        open_amount = await payables.compute_open_amount(
            session, tenant_id=tenant_id, payable=payable
        )
        if open_amount > 0:
            candidates.append(
                PayableBankCandidate(
                    payable=payable,
                    match_amount=open_amount,
                    existing_payment=None,
                )
            )
            continue
        active = await payables._active_movements(
            session, tenant_id=tenant_id, payable_id=payable.id
        )
        if (
            len(active) == 1
            and active[0].movement_type == "PAYMENT"
            and not (active[0].support_reference or "").strip()
            and active[0].amount == payable.total
        ):
            candidates.append(
                PayableBankCandidate(
                    payable=payable,
                    match_amount=payable.total,
                    existing_payment=active[0],
                )
            )
    return candidates


async def _stored_transactions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    transaction_ids: list[str],
) -> dict[str, StoredBankTransaction]:
    if not transaction_ids:
        return {}
    rows = list(
        await session.scalars(
            select(StoredBankTransaction).where(
                StoredBankTransaction.tenant_id == tenant_id,
                StoredBankTransaction.transaction_id.in_(transaction_ids),
            )
        )
    )
    return {row.transaction_id: row for row in rows}


async def _persist_statement(
    session: AsyncSession,
    *,
    context: AuthContext,
    parsed: ParsedBankStatement,
    file_name: str,
    period: date,
    transactions: list[BankTransaction],
) -> dict[str, StoredBankTransaction]:
    statement_import = await session.scalar(
        select(BankStatementImport).where(
            BankStatementImport.tenant_id == context.tenant_id,
            BankStatementImport.source_sha256 == parsed.source_sha256,
        )
    )
    if statement_import is None:
        statement_import = BankStatementImport(
            tenant_id=context.tenant_id,
            source_sha256=parsed.source_sha256,
            file_name=file_name,
            account_masked=parsed.account_masked,
            period=period,
            imported_by=context.actor_id,
        )
        session.add(statement_import)
        await session.flush()
    stored = await _stored_transactions(
        session,
        tenant_id=context.tenant_id,
        transaction_ids=[item.transaction_id for item in transactions],
    )
    for transaction in transactions:
        if transaction.transaction_id in stored:
            continue
        row = StoredBankTransaction(
            tenant_id=context.tenant_id,
            statement_import_id=statement_import.id,
            transaction_id=transaction.transaction_id,
            direction=transaction.direction,
            occurred_at=transaction.occurred_at,
            reference=transaction.reference,
            description=transaction.description,
            amount=transaction.amount,
            classification=_debit_classification(transaction.description),
        )
        session.add(row)
        stored[transaction.transaction_id] = row
    await session.flush()
    return stored


async def _allocated_transaction_ids(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    stored: dict[str, StoredBankTransaction],
) -> set[str]:
    if not stored:
        return set()
    ids_by_pk = {row.id: key for key, row in stored.items()}
    allocated = list(
        await session.scalars(
            select(BankTransactionAllocation.bank_transaction_id).where(
                BankTransactionAllocation.tenant_id == tenant_id,
                BankTransactionAllocation.bank_transaction_id.in_(list(ids_by_pk)),
            )
        )
    )
    return {ids_by_pk[item] for item in allocated}


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
    debit_allocations: list[BankDebitAllocationInput] | None = None,
    process_debits: bool = False,
) -> BankStatementImportRead:
    parsed = parse_bank_statement(content)
    period_credits = [
        credit
        for credit in parsed.credits
        if credit.occurred_at.year == period.year and credit.occurred_at.month == period.month
    ]
    period_debits = [
        debit
        for debit in parsed.debits
        if debit.occurred_at.year == period.year and debit.occurred_at.month == period.month
    ]
    period_transactions = [*period_credits, *period_debits]
    stored_transactions = (
        await _persist_statement(
            session,
            context=context,
            parsed=parsed,
            file_name=file_name,
            period=period,
            transactions=period_transactions,
        )
        if apply
        else await _stored_transactions(
            session,
            tenant_id=context.tenant_id,
            transaction_ids=[item.transaction_id for item in period_transactions],
        )
    )
    allocated_transaction_ids = await _allocated_transaction_ids(
        session,
        tenant_id=context.tenant_id,
        stored=stored_transactions,
    )
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

    credits_by_amount: dict[Decimal, list[BankTransaction]] = defaultdict(list)
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
                    idempotency_key=_child_idempotency_key(
                        idempotency_key,
                        operation="reverse",
                        transaction_id=credit.transaction_id,
                    ),
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
                idempotency_key=_child_idempotency_key(
                    idempotency_key,
                    operation="payment",
                    transaction_id=credit.transaction_id,
                ),
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
                idempotency_key=_child_idempotency_key(
                    idempotency_key,
                    operation="manual-correction",
                    transaction_id=credit.transaction_id,
                ),
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
    if apply:
        credit_targets = {
            match.transaction_id: match.receivable_id for match in matches
        }
        for transaction_id, receivable_id in credit_targets.items():
            if transaction_id in allocated_transaction_ids:
                continue
            stored = stored_transactions[transaction_id]
            match = next(item for item in matches if item.transaction_id == transaction_id)
            session.add(
                BankTransactionAllocation(
                    tenant_id=context.tenant_id,
                    bank_transaction_id=stored.id,
                    payable_id=None,
                    receivable_id=receivable_id,
                    amount=match.amount,
                )
            )
            allocated_transaction_ids.add(transaction_id)
        await session.flush()

    debit_matches: list[BankStatementDebitMatchRead] = []
    debit_suggestions: list[BankStatementDebitSuggestionRead] = []
    if process_debits:
        payable_candidates = await _payable_candidates(
            session, tenant_id=context.tenant_id, period=period
        )
        candidates_by_id = {
            candidate.payable.id: candidate for candidate in payable_candidates
        }
        pending_debits = [
            item
            for item in period_debits
            if item.transaction_id not in allocated_transaction_ids
        ]
        debits_by_id = {item.transaction_id: item for item in pending_debits}
        planned: list[tuple[BankTransaction, PayableBankCandidate, Decimal]] = []
        used_payables: set[uuid.UUID] = set()
        allocations_by_transaction: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        manual_amounts: dict[tuple[str, uuid.UUID], Decimal] = defaultdict(
            lambda: Decimal("0.00")
        )
        for allocation in debit_allocations or []:
            manual_amounts[(allocation.transaction_id, allocation.payable_id)] += (
                allocation.amount
            )
        for (transaction_id, payable_id), allocation_amount in manual_amounts.items():
            debit = debits_by_id.get(transaction_id)
            payable_candidate = candidates_by_id.get(payable_id)
            if debit is None or payable_candidate is None:
                raise HTTPException(
                    status_code=422,
                    detail="Debit allocation references an unavailable transaction or payable",
                )
            allocations_by_transaction[debit.transaction_id] += allocation_amount
            if allocations_by_transaction[debit.transaction_id] > debit.amount:
                raise HTTPException(
                    status_code=422,
                    detail="Debit allocations exceed the bank transaction amount",
                )
            if allocation_amount > payable_candidate.match_amount:
                raise HTTPException(
                    status_code=422,
                    detail="Debit allocation exceeds the payable open amount",
                )
            if payable_candidate.existing_payment is not None and (
                allocation_amount != payable_candidate.existing_payment.amount
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Existing paid expense evidence must match the full payment",
                )
            planned.append((debit, payable_candidate, allocation_amount))
            used_payables.add(payable_candidate.payable.id)

        manually_planned_transactions = {item[0].transaction_id for item in planned}
        auto_debits = [
            item
            for item in pending_debits
            if item.transaction_id not in manually_planned_transactions
            and _debit_classification(item.description) == "UNCLASSIFIED"
        ]
        debits_by_amount: dict[Decimal, list[BankTransaction]] = defaultdict(list)
        payable_candidates_by_amount: dict[
            Decimal, list[PayableBankCandidate]
        ] = defaultdict(list)
        for debit in auto_debits:
            debits_by_amount[debit.amount].append(debit)
        for payable_candidate in payable_candidates:
            if payable_candidate.payable.id not in used_payables:
                payable_candidates_by_amount[payable_candidate.match_amount].append(
                    payable_candidate
                )
        for amount, amount_debits in debits_by_amount.items():
            payable_amount_candidates = [
                payable_candidate
                for payable_candidate in payable_candidates_by_amount.get(amount, [])
                if payable_candidate.payable.issue_date
                <= amount_debits[0].occurred_at.date()
            ]
            if len(amount_debits) != 1 or len(payable_amount_candidates) != 1:
                continue
            planned.append((amount_debits[0], payable_amount_candidates[0], amount))
            used_payables.add(payable_amount_candidates[0].payable.id)

        matched_debit_ids: set[str] = set()
        for debit, payable_candidate, allocated_amount in planned:
            matched_debit_ids.add(debit.transaction_id)
            links_existing = payable_candidate.existing_payment is not None
            status = "MATCHED"
            detail = (
                "Adjuntará el banco al pago ya registrado"
                if links_existing
                else "Lista para registrar"
            )
            if apply:
                reference = _bank_reference(debit)
                if payable_candidate.existing_payment is not None:
                    payable_candidate.existing_payment.support_reference = reference
                    status = "EVIDENCE_LINKED"
                    detail = "Respaldo bancario enlazado sin duplicar el pago"
                else:
                    await payables.record_payment(
                        session,
                        context,
                        payable_id=payable_candidate.payable.id,
                        data=PayablePaymentCreate(
                            amount=allocated_amount,
                            payment_date=debit.occurred_at.date(),
                            method="TRANSFER",
                            reference=reference,
                        ),
                    )
                    status = "REGISTERED"
                    detail = "Pago a proveedor registrado"
                stored = stored_transactions[debit.transaction_id]
                session.add(
                    BankTransactionAllocation(
                        tenant_id=context.tenant_id,
                        bank_transaction_id=stored.id,
                        payable_id=payable_candidate.payable.id,
                        receivable_id=None,
                        amount=allocated_amount,
                    )
                )
            debit_matches.append(
                BankStatementDebitMatchRead(
                    transaction_id=debit.transaction_id,
                    payment_date=debit.occurred_at.date(),
                    reference=debit.reference,
                    description=debit.description,
                    amount=debit.amount,
                    payable_id=payable_candidate.payable.id,
                    supplier_name=payable_candidate.payable.supplier_name,
                    document_number=payable_candidate.payable.document_number,
                    payable_total=payable_candidate.payable.total,
                    allocated_amount=allocated_amount,
                    links_existing_payment=links_existing,
                    status=status,
                    detail=detail,
                )
            )
        if apply:
            await session.flush()

        for debit in pending_debits:
            if debit.transaction_id in matched_debit_ids:
                continue
            classification = _debit_classification(debit.description)
            rule = await payables.matching_rule(
                session,
                tenant_id=context.tenant_id,
                description=debit.description,
                amount=debit.amount,
                account_last4=parsed.account_last4,
            )
            effective_classification = (
                "EXPENSE_CANDIDATE" if rule is not None else classification
            )
            detail = (
                "Regla encontrada; confirma los datos para crear el gasto"
                if rule is not None
                else {
                    "BANK_FEE": "Comisión bancaria pendiente de confirmación",
                    "BANK_TAX": "Impuesto bancario pendiente de confirmación",
                    "CARD_SETTLEMENT": "Liquidación de tarjeta; no se reparte automáticamente",
                    "INTERNAL_TRANSFER": "Posible transferencia interna; no crea gasto",
                }.get(classification, "Sin cruce; requiere revisión")
            )
            debit_suggestions.append(
                BankStatementDebitSuggestionRead(
                    transaction_id=debit.transaction_id,
                    payment_date=debit.occurred_at.date(),
                    reference=debit.reference,
                    description=debit.description,
                    amount=debit.amount,
                    classification=effective_classification,
                    rule_id=rule.id if rule is not None else None,
                    rule_name=rule.name if rule is not None else None,
                    suggested_category=rule.category if rule is not None else None,
                    suggested_supplier_name=(
                        rule.supplier_name if rule is not None else None
                    ),
                    suggested_tax_classification=(
                        rule.tax_classification if rule is not None else None
                    ),
                    detail=detail,
                )
            )
    already_imported_count = len(period_credits) - len(pending_credits)
    return BankStatementImportRead(
        period=period.strftime("%Y-%m"),
        file_name=file_name,
        source_sha256=parsed.source_sha256,
        account_masked=parsed.account_masked,
        total_rows=parsed.total_rows,
        credit_rows=len(period_credits),
        debit_rows=len(period_debits),
        outside_period_credit_count=len(parsed.credits) - len(period_credits),
        outside_period_debit_count=len(parsed.debits) - len(period_debits),
        matched_count=len(matches),
        unmatched_credit_count=len(pending_credits) - len(matches),
        ignored_debit_count=parsed.debit_rows if not process_debits else 0,
        payable_matched_count=len(debit_matches),
        unmatched_debit_count=(
            len(period_debits) - len({item.transaction_id for item in debit_matches})
            if process_debits
            else len(period_debits)
        ),
        rule_suggestion_count=sum(
            item.rule_id is not None for item in debit_suggestions
        ),
        already_imported_count=already_imported_count,
        manual_correction_count=len(manual_corrections),
        matches=matches,
        manual_corrections=manual_corrections,
        debit_matches=debit_matches,
        debit_suggestions=debit_suggestions,
    )

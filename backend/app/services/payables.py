from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.masters import Party
from app.models.payables import (
    ExpenseRecognitionRule,
    Payable,
    PayableInstallment,
    PayableMovement,
    SupplierPaymentSchedule,
)
from app.models.tax import FiscalDocument
from app.schemas.payables import (
    ExpenseRuleCreate,
    PayableAdjustmentCreate,
    PayableCreate,
    PayablePaymentCreate,
    PayableRead,
    PaymentScheduleCreate,
)
from app.services import analytics


def _reversed_movement_ids(tenant_id: uuid.UUID) -> Select[tuple[uuid.UUID | None]]:
    return select(PayableMovement.reversed_movement_id).where(
        PayableMovement.tenant_id == tenant_id,
        PayableMovement.movement_type == "REVERSAL",
        PayableMovement.reversed_movement_id.is_not(None),
    )


async def lock_payable(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable_id: uuid.UUID
) -> Payable:
    payable = await session.scalar(
        select(Payable)
        .where(Payable.tenant_id == tenant_id, Payable.id == payable_id)
        .with_for_update()
    )
    if payable is None:
        raise HTTPException(status_code=404, detail="Payable not found")
    return payable


async def _installments(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable_id: uuid.UUID
) -> list[PayableInstallment]:
    return list(
        await session.scalars(
            select(PayableInstallment)
            .where(
                PayableInstallment.tenant_id == tenant_id,
                PayableInstallment.payable_id == payable_id,
            )
            .order_by(PayableInstallment.due_date, PayableInstallment.sequence)
        )
    )


async def _active_movements(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable_id: uuid.UUID
) -> list[PayableMovement]:
    return list(
        await session.scalars(
            select(PayableMovement).where(
                PayableMovement.tenant_id == tenant_id,
                PayableMovement.payable_id == payable_id,
                PayableMovement.movement_type != "REVERSAL",
                PayableMovement.id.not_in(_reversed_movement_ids(tenant_id)),
            )
        )
    )


async def compute_open_amount(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable: Payable
) -> Decimal:
    active = await _active_movements(session, tenant_id=tenant_id, payable_id=payable.id)
    applied = sum((movement.amount for movement in active), Decimal("0.00"))
    return max(payable.total - applied, Decimal("0.00"))


def _public_status(payable: Payable, open_amount: Decimal) -> str:
    if payable.status == "VOID":
        return "VOIDED"
    if open_amount == Decimal("0.00"):
        return "SETTLED"
    if open_amount < payable.total:
        return "PARTIAL"
    return "OPEN"


async def to_read(session: AsyncSession, *, tenant_id: uuid.UUID, payable: Payable) -> PayableRead:
    open_amount = await compute_open_amount(session, tenant_id=tenant_id, payable=payable)
    return PayableRead(
        id=payable.id,
        supplier_id=payable.supplier_id,
        supplier_name=payable.supplier_name,
        fiscal_document_id=payable.fiscal_document_id,
        description=payable.description,
        category=payable.category,
        document_type=payable.document_type,
        document_number=payable.document_number,
        issue_date=payable.issue_date,
        due_date=payable.due_date,
        total=payable.total,
        open_amount=open_amount,
        currency=payable.currency,
        status=_public_status(payable, open_amount),
        tax_classification=payable.tax_classification,
        evidence_status=payable.evidence_status,
        support_reference=payable.support_reference,
        analytic_assignments=await analytics.list_assignments(
            session,
            tenant_id=tenant_id,
            target_type="PAYABLE",
            target_id=payable.id,
        ),
    )


async def list_payables(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: str | None = None,
    due_before: date | None = None,
    analytic_value_ids: list[uuid.UUID] | None = None,
) -> list[PayableRead]:
    query = select(Payable).where(Payable.tenant_id == tenant_id)
    if due_before is not None:
        query = query.where(Payable.due_date <= due_before)
    if analytic_value_ids:
        matching_ids = await analytics.target_ids_matching_values(
            session,
            tenant_id=tenant_id,
            target_type="PAYABLE",
            value_ids=analytic_value_ids,
        )
        query = query.where(Payable.id.in_(matching_ids))
    entities = list(
        await session.scalars(query.order_by(Payable.issue_date.desc(), Payable.created_at.desc()))
    )
    result = [await to_read(session, tenant_id=tenant_id, payable=item) for item in entities]
    return [item for item in result if status is None or item.status == status]


async def get_payable(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable_id: uuid.UUID
) -> PayableRead:
    payable = await session.scalar(
        select(Payable).where(Payable.tenant_id == tenant_id, Payable.id == payable_id)
    )
    if payable is None:
        raise HTTPException(status_code=404, detail="Payable not found")
    return await to_read(session, tenant_id=tenant_id, payable=payable)


async def _validate_supplier(
    session: AsyncSession, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID | None
) -> Party | None:
    if supplier_id is None:
        return None
    supplier = await session.scalar(
        select(Party).where(Party.tenant_id == tenant_id, Party.id == supplier_id)
    )
    if supplier is None or "SUPPLIER" not in supplier.roles:
        raise HTTPException(status_code=422, detail="Supplier is not valid for this tenant")
    return supplier


async def create_payable(
    session: AsyncSession,
    context: AuthContext,
    data: PayableCreate,
) -> PayableRead:
    supplier = await _validate_supplier(
        session, tenant_id=context.tenant_id, supplier_id=data.supplier_id
    )
    due_date = data.due_date or data.issue_date
    if data.installments:
        due_date = min(item.due_date for item in data.installments)
    payable = Payable(
        tenant_id=context.tenant_id,
        supplier_id=data.supplier_id,
        supplier_name=data.supplier_name or (supplier.name if supplier is not None else None),
        fiscal_document_id=None,
        description=data.description,
        category=data.category,
        document_type=data.document_type,
        document_number=data.document_number,
        issue_date=data.issue_date,
        due_date=due_date,
        total=data.total,
        currency="USD",
        status="OPEN",
        tax_classification=data.tax_classification,
        evidence_status=data.evidence_status,
        support_reference=data.support_reference,
    )
    session.add(payable)
    await session.flush()
    await analytics.replace_assignments(
        session,
        context,
        target_type="PAYABLE",
        target_id=payable.id,
        value_ids=data.analytic_value_ids,
    )
    installment_values = (
        [(item.due_date, item.amount) for item in data.installments]
        if data.installments
        else [(due_date, data.total)]
    )
    for sequence, (installment_due_date, installment_amount) in enumerate(
        installment_values, start=1
    ):
        session.add(
            PayableInstallment(
                tenant_id=context.tenant_id,
                payable_id=payable.id,
                sequence=sequence,
                due_date=installment_due_date,
                amount=installment_amount,
            )
        )
    await session.flush()
    if data.payment_timing == "PAID_NOW":
        await record_payment(
            session,
            context,
            payable_id=payable.id,
            data=PayablePaymentCreate(
                amount=data.total,
                payment_date=data.payment_date or data.issue_date,
                method=data.payment_method,
                reference=data.payment_reference,
            ),
        )
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def update_payable_analytic_assignments(
    session: AsyncSession,
    context: AuthContext,
    payable_id: uuid.UUID,
    *,
    value_ids: list[uuid.UUID],
) -> PayableRead:
    payable = await lock_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)
    if (
        await compute_open_amount(session, tenant_id=context.tenant_id, payable=payable)
        != payable.total
    ):
        raise HTTPException(
            status_code=409,
            detail="Analytic classifications cannot change after a payable has movements",
        )
    await analytics.replace_assignments(
        session,
        context,
        target_type="PAYABLE",
        target_id=payable.id,
        value_ids=value_ids,
    )
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def create_from_fiscal_document(
    session: AsyncSession,
    context: AuthContext,
    *,
    document_id: uuid.UUID,
) -> PayableRead:
    document = await session.scalar(
        select(FiscalDocument).where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.id == document_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Fiscal document not found")
    payable = await sync_fiscal_document(session, context, document=document)
    if payable is None:
        raise HTTPException(
            status_code=422,
            detail="Fiscal document cannot create an operational payable",
        )
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def _record_application(
    session: AsyncSession,
    context: AuthContext,
    *,
    payable: Payable,
    movement_type: str,
    amount: Decimal,
    effective_date: date,
    method: str | None,
    reference: str | None,
) -> None:
    open_amount = await compute_open_amount(session, tenant_id=context.tenant_id, payable=payable)
    if amount > open_amount:
        raise HTTPException(status_code=422, detail="Movement exceeds payable open amount")
    installments = await _installments(session, tenant_id=context.tenant_id, payable_id=payable.id)
    active = await _active_movements(session, tenant_id=context.tenant_id, payable_id=payable.id)
    applied_by_installment: dict[uuid.UUID, Decimal] = {}
    for movement in active:
        applied_by_installment[movement.installment_id] = (
            applied_by_installment.get(movement.installment_id, Decimal("0.00")) + movement.amount
        )
    remaining = amount
    for installment in installments:
        installment_open = installment.amount - applied_by_installment.get(
            installment.id, Decimal("0.00")
        )
        if installment_open <= 0:
            continue
        allocated = min(installment_open, remaining)
        session.add(
            PayableMovement(
                tenant_id=context.tenant_id,
                payable_id=payable.id,
                installment_id=installment.id,
                movement_type=movement_type,
                amount=allocated,
                effective_date=effective_date,
                method=method,
                support_reference=reference,
                reversed_movement_id=None,
                actor_id=context.actor_id,
            )
        )
        remaining -= allocated
        if remaining == 0:
            break
    await session.flush()
    new_open = open_amount - amount
    payable.status = "PAID" if new_open == 0 else "PARTIALLY_PAID"


async def record_payment(
    session: AsyncSession,
    context: AuthContext,
    *,
    payable_id: uuid.UUID,
    data: PayablePaymentCreate,
) -> PayableRead:
    payable = await lock_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)
    if payable.status == "VOID":
        raise HTTPException(status_code=422, detail="Voided payable cannot receive payments")
    await _record_application(
        session,
        context,
        payable=payable,
        movement_type="PAYMENT",
        amount=data.amount,
        effective_date=data.payment_date,
        method=data.method,
        reference=data.reference,
    )
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def record_adjustment(
    session: AsyncSession,
    context: AuthContext,
    *,
    payable_id: uuid.UUID,
    data: PayableAdjustmentCreate,
) -> PayableRead:
    payable = await lock_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)
    await _record_application(
        session,
        context,
        payable=payable,
        movement_type=data.movement_type,
        amount=data.amount,
        effective_date=data.effective_date,
        method=None,
        reference=data.reference,
    )
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def reverse_movement(
    session: AsyncSession,
    context: AuthContext,
    *,
    payable_id: uuid.UUID,
    movement_id: uuid.UUID,
    reason: str,
    effective_date: date,
) -> PayableRead:
    payable = await lock_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)
    movement = await session.scalar(
        select(PayableMovement).where(
            PayableMovement.tenant_id == context.tenant_id,
            PayableMovement.payable_id == payable.id,
            PayableMovement.id == movement_id,
            PayableMovement.movement_type != "REVERSAL",
        )
    )
    if movement is None:
        raise HTTPException(status_code=404, detail="Payable movement not found")
    reversed_exists = await session.scalar(
        select(PayableMovement.id).where(
            PayableMovement.tenant_id == context.tenant_id,
            PayableMovement.reversed_movement_id == movement.id,
        )
    )
    if reversed_exists is not None:
        raise HTTPException(status_code=409, detail="Payable movement was already reversed")
    session.add(
        PayableMovement(
            tenant_id=context.tenant_id,
            payable_id=payable.id,
            installment_id=movement.installment_id,
            movement_type="REVERSAL",
            amount=movement.amount,
            effective_date=effective_date,
            method=None,
            support_reference=reason,
            reversed_movement_id=movement.id,
            actor_id=context.actor_id,
        )
    )
    await session.flush()
    open_amount = await compute_open_amount(session, tenant_id=context.tenant_id, payable=payable)
    payable.status = "OPEN" if open_amount == payable.total else "PARTIALLY_PAID"
    return await to_read(session, tenant_id=context.tenant_id, payable=payable)


async def list_movements(
    session: AsyncSession, *, tenant_id: uuid.UUID, payable_id: uuid.UUID
) -> list[PayableMovement]:
    await get_payable(session, tenant_id=tenant_id, payable_id=payable_id)
    return list(
        await session.scalars(
            select(PayableMovement)
            .where(
                PayableMovement.tenant_id == tenant_id,
                PayableMovement.payable_id == payable_id,
            )
            .order_by(PayableMovement.created_at.desc())
        )
    )


async def schedule_payment(
    session: AsyncSession,
    context: AuthContext,
    *,
    payable_id: uuid.UUID,
    data: PaymentScheduleCreate,
) -> SupplierPaymentSchedule:
    payable = await lock_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)
    open_amount = await compute_open_amount(session, tenant_id=context.tenant_id, payable=payable)
    if data.amount > open_amount:
        raise HTTPException(status_code=422, detail="Schedule exceeds payable open amount")
    schedule = SupplierPaymentSchedule(
        tenant_id=context.tenant_id,
        payable_id=payable.id,
        scheduled_date=data.scheduled_date,
        amount=data.amount,
        priority=data.priority,
        status="SCHEDULED",
    )
    session.add(schedule)
    await session.flush()
    return schedule


async def list_rules(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[ExpenseRecognitionRule]:
    return list(
        await session.scalars(
            select(ExpenseRecognitionRule)
            .where(ExpenseRecognitionRule.tenant_id == tenant_id)
            .order_by(ExpenseRecognitionRule.name)
        )
    )


async def create_rule(
    session: AsyncSession, context: AuthContext, data: ExpenseRuleCreate
) -> ExpenseRecognitionRule:
    rule = ExpenseRecognitionRule(
        tenant_id=context.tenant_id,
        **data.model_dump(by_alias=False),
    )
    session.add(rule)
    await session.flush()
    return rule


async def matching_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    description: str,
    amount: Decimal,
    account_last4: str,
) -> ExpenseRecognitionRule | None:
    rules = await list_rules(session, tenant_id=tenant_id)
    normalized = " ".join(description.casefold().split())
    matches = [
        rule
        for rule in rules
        if rule.active
        and " ".join(rule.description_pattern.casefold().split()) in normalized
        and (rule.account_last4 is None or rule.account_last4 == account_last4)
        and (rule.amount_min is None or amount >= rule.amount_min)
        and (rule.amount_max is None or amount <= rule.amount_max)
    ]
    return matches[0] if len(matches) == 1 else None


def _document_number(document: FiscalDocument) -> str | None:
    parts = (
        document.establishment_code,
        document.emission_point_code,
        document.sequential,
    )
    return "-".join(str(part) for part in parts) if all(parts) else None


async def sync_fiscal_document(
    session: AsyncSession,
    context: AuthContext,
    *,
    document: FiscalDocument,
) -> Payable | None:
    if document.direction != "RECIBIDO":
        return None
    if document.doc_type == "NOTA_CREDITO":
        if not document.related_access_key:
            return None
        source = await session.scalar(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.access_key == document.related_access_key,
            )
        )
        if source is None:
            return None
        payable = await session.scalar(
            select(Payable).where(
                Payable.tenant_id == context.tenant_id,
                Payable.fiscal_document_id == source.id,
            )
        )
        if payable is None:
            return None
        duplicate = await session.scalar(
            select(PayableMovement.id).where(
                PayableMovement.tenant_id == context.tenant_id,
                PayableMovement.payable_id == payable.id,
                PayableMovement.movement_type == "CREDIT_NOTE",
                PayableMovement.support_reference == document.access_key,
            )
        )
        if duplicate is None:
            open_amount = await compute_open_amount(
                session, tenant_id=context.tenant_id, payable=payable
            )
            if document.total <= open_amount:
                await _record_application(
                    session,
                    context,
                    payable=payable,
                    movement_type="CREDIT_NOTE",
                    amount=document.total,
                    effective_date=document.issue_date,
                    method=None,
                    reference=document.access_key,
                )
        return payable
    if document.doc_type not in {"FACTURA", "LIQUIDACION", "NOTA_DEBITO"}:
        return None
    existing = await session.scalar(
        select(Payable).where(
            Payable.tenant_id == context.tenant_id,
            Payable.fiscal_document_id == document.id,
        )
    )
    if existing is not None:
        existing.supplier_name = document.counterparty_name
        existing.document_number = _document_number(document)
        existing.evidence_status = "PRELIMINARY" if document.is_preliminary else "FISCAL_XML"
        return existing
    manual_matches = list(
        await session.scalars(
            select(Payable).where(
                Payable.tenant_id == context.tenant_id,
                Payable.fiscal_document_id.is_(None),
                Payable.issue_date == document.issue_date,
                Payable.total == document.total,
                func.lower(Payable.supplier_name) == (document.counterparty_name or "").lower(),
            )
        )
    )
    if len(manual_matches) == 1:
        payable = manual_matches[0]
        payable.fiscal_document_id = document.id
        payable.document_number = _document_number(document)
        payable.evidence_status = "PRELIMINARY" if document.is_preliminary else "FISCAL_XML"
        return payable
    payable = Payable(
        tenant_id=context.tenant_id,
        supplier_id=None,
        supplier_name=document.counterparty_name,
        fiscal_document_id=document.id,
        description=f"Compra {(_document_number(document) or document.access_key or '').strip()}",
        category="Sin clasificar",
        document_type={
            "FACTURA": "INVOICE",
            "LIQUIDACION": "LIQUIDATION",
            "NOTA_DEBITO": "DEBIT_NOTE",
        }[document.doc_type],
        document_number=_document_number(document),
        issue_date=document.issue_date,
        due_date=document.issue_date,
        total=document.total,
        currency="USD",
        status="OPEN",
        tax_classification="DEDUCTIBLE_PENDING_REVIEW",
        evidence_status="PRELIMINARY" if document.is_preliminary else "FISCAL_XML",
        support_reference=document.access_key,
    )
    session.add(payable)
    await session.flush()
    session.add(
        PayableInstallment(
            tenant_id=context.tenant_id,
            payable_id=payable.id,
            sequence=1,
            due_date=document.issue_date,
            amount=document.total,
        )
    )
    await session.flush()
    return payable

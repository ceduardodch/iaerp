"""Receivable balances, payment promises and confirmed individual reminders."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import FISCAL_TIMEZONE, today_in_fiscal_timezone
from app.models.billing import SalesDocument
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.platform import OutboxEvent
from app.models.receivables import (
    CollectionPolicy,
    CollectionReminder,
    Movement,
    Receivable,
    ReceivableInstallment,
)
from app.schemas.ios_collections import (
    CollectionAccount,
    CollectionInstallment,
    ReminderConfirmation,
)
from app.services import receivables

NATIVE_REMINDER_EVENT = "collection.email.confirmed"
ZERO = Decimal("0.00")


def shown_status(reminder: CollectionReminder) -> str:
    if reminder.delivery_status == "UNCERTAIN":
        return "UNCERTAIN"
    if reminder.status in {"SKIPPED", "STUBBED"}:
        return "CANCELLED"
    return reminder.status


def _blocked_reason(
    account: Receivable,
    party: Party,
    policy: CollectionPolicy | None,
    reminders: list[CollectionReminder],
    today: date,
    day_start: datetime,
) -> str | None:
    if not policy or not policy.enabled:
        return (
            "La cobranza está pausada. Pide al administrador que active la política de la empresa."
        )
    if party.consent_opt_out:
        return "El cliente pidió dejar de recibir avisos de cobro."
    if not party.email:
        return "Agrega un correo al cliente para enviar el recordatorio."
    if not account.collection_enabled:
        return "Habilita los recordatorios para esta factura."
    if account.promised_date and account.promised_date >= today:
        return "Los avisos están pausados hasta la fecha prometida inclusive."
    for reminder in reminders:
        status = shown_status(reminder)
        if status == "UNCERTAIN":
            return "El proveedor aún no confirma el envío anterior."
        if status in {"PENDING", "PROCESSING"}:
            return "Ya hay un recordatorio pendiente para esta factura."
        sent_at = reminder.sent_at or reminder.created_at
        if status == "SENT" and sent_at.replace(tzinfo=UTC) >= day_start:
            return "Ya se envió un recordatorio para esta factura hoy."
    return None


async def accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    *,
    exclude_reminder_id: uuid.UUID | None = None,
) -> list[CollectionAccount]:
    """Bulk read active balances using active (unreversed) movements per installment."""
    m, i, r, d = Movement, ReceivableInstallment, Receivable, SalesDocument
    move_query = select(
        m.installment_id,
        func.sum(m.amount).label("applied"),
        func.sum(case((m.movement_type == "PAYMENT", m.amount), else_=0)).label("cash"),
        func.sum(case((m.movement_type == "RETENTION", m.amount), else_=0)).label("retained"),
    ).where(
        m.tenant_id == tenant_id,
        m.reversed_movement_id.is_(None),
        m.id.not_in(receivables._reversed_movement_ids(tenant_id)),
    )
    if account_id is not None:
        move_query = move_query.where(m.receivable_id == account_id)
    applied = move_query.group_by(m.installment_id).subquery()
    balance = i.amount - func.coalesce(applied.c.applied, ZERO)
    installment_query = (
        select(
            i.receivable_id,
            func.sum(balance).label("balance"),
            func.sum(applied.c.cash).label("cash"),
            func.sum(applied.c.retained).label("retained"),
            func.min(case((balance > 0, i.due_date))).label("due"),
            func.count(i.id).label("count"),
        )
        .outerjoin(applied, applied.c.installment_id == i.id)
        .where(i.tenant_id == tenant_id)
    )
    if account_id is not None:
        installment_query = installment_query.where(i.receivable_id == account_id)
    amounts = installment_query.group_by(i.receivable_id).subquery()
    stmt = (
        select(
            r,
            Party,
            d.status,
            d.sequential,
            Establishment.code,
            EmissionPoint.code,
            amounts.c.balance,
            amounts.c.cash,
            amounts.c.retained,
            amounts.c.due,
            amounts.c["count"],
        )
        .select_from(r)
        .join(d, d.id == r.sales_document_id)
        .join(Party, Party.id == r.party_id)
        .join(
            Establishment,
            Establishment.id == d.establishment_id,
        )
        .join(EmissionPoint, EmissionPoint.id == d.emission_point_id)
        .join(
            amounts,
            amounts.c.receivable_id == r.id,
        )
        .where(
            r.tenant_id == tenant_id,
            d.tenant_id == tenant_id,
            Party.tenant_id == tenant_id,
            Establishment.tenant_id == tenant_id,
            EmissionPoint.tenant_id == tenant_id,
            r.status.in_(("OPEN", "PARTIALLY_PAID")),
            d.status != "VOIDED",
            amounts.c.balance > 0,
        )
        .order_by(Party.name, amounts.c.due, r.id)
    )
    if account_id is not None:
        stmt = stmt.where(r.id == account_id)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    today = today_in_fiscal_timezone()
    day_start = datetime.combine(today, time.min, FISCAL_TIMEZONE).astimezone(UTC)
    policy = await session.get(CollectionPolicy, tenant_id)
    by_account: dict[uuid.UUID, list[CollectionReminder]] = defaultdict(list)
    ids = [row[0].id for row in rows]
    installments: dict[uuid.UUID, list[CollectionInstallment]] = defaultdict(list)
    for rid, iid, seq, day, remaining in await session.execute(
        select(i.receivable_id, i.id, i.sequence, i.due_date, balance)
        .outerjoin(applied, applied.c.installment_id == i.id)
        .where(i.tenant_id == tenant_id, i.receivable_id.in_(ids))
        .order_by(i.receivable_id, i.sequence)
    ):
        installments[rid].append(
            CollectionInstallment(id=iid, sequence=seq, due_date=day, open_amount=remaining)
        )
    reminders = (
        select(CollectionReminder)
        .where(
            CollectionReminder.tenant_id == tenant_id,
            CollectionReminder.receivable_id.in_(ids),
            CollectionReminder.channel == "EMAIL",
            # Future automatic appointments do not block a manual contact today.
            (CollectionReminder.status != "PENDING")
            | (CollectionReminder.scheduled_at <= datetime.now(UTC)),
        )
        .order_by(CollectionReminder.created_at.desc(), CollectionReminder.id.desc())
    )
    if exclude_reminder_id is not None:
        reminders = reminders.where(CollectionReminder.id != exclude_reminder_id)
    for record in await session.scalars(reminders):
        if record.receivable_id is not None:
            by_account[record.receivable_id].append(record)
    output = []
    for (
        account,
        party,
        fiscal_status,
        sequential,
        branch,
        point,
        net,
        cash,
        retained,
        due,
        count,
    ) in rows:
        history = by_account[account.id]
        last = history[0] if history else None
        blocked = _blocked_reason(account, party, policy, history, today, day_start)
        if account.currency != "USD":
            blocked = "Esta cuenta requiere una plantilla en la moneda de la factura."
        if fiscal_status != "AUTHORIZED":
            blocked = "La factura requiere autorización para gestionar la cobranza."
        output.append(
            CollectionAccount(
                id=account.id,
                party_id=party.id,
                customer_name=party.name,
                invoice_number=f"{branch}-{point}-{sequential}",
                currency=account.currency,
                original_amount=account.original_amount,
                cash_amount=cash or ZERO,
                retention_amount=retained or ZERO,
                open_amount=net,
                due_date=due,
                overdue=due < today,
                installments=installments[account.id],
                installment_count=count,
                promised_date=account.promised_date,
                email=party.email,
                collection_enabled=account.collection_enabled,
                can_enable_reminders=bool(
                    policy
                    and policy.enabled
                    and not party.consent_opt_out
                    and fiscal_status == "AUTHORIZED"
                    and party.email
                    and not account.collection_enabled
                    and account.currency == "USD"
                ),
                reminder_blocked_reason=blocked,
                last_reminder_at=(last.sent_at or last.created_at) if last else None,
                last_reminder_status=shown_status(last) if last else None,
            )
        )
    return output


async def detail(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    exclude_reminder_id: uuid.UUID | None = None,
) -> CollectionAccount:
    rows = await accounts(session, tenant_id, account_id, exclude_reminder_id=exclude_reminder_id)
    if not rows:
        raise HTTPException(404, "Esta cuenta ya no tiene un saldo vigente por cobrar.")
    return rows[0]


def require_current_confirmation(
    view: CollectionAccount, confirmation: ReminderConfirmation
) -> None:
    if view.reminder_blocked_reason:
        raise HTTPException(409, view.reminder_blocked_reason)
    if (view.email, view.open_amount, view.due_date) != (
        confirmation.expected_recipient,
        confirmation.expected_open_amount,
        confirmation.expected_due_date,
    ):
        raise HTTPException(
            409,
            "Cambió el destinatario, el saldo o el vencimiento. Revisa la cuenta antes de enviar.",
        )


async def queue_email(
    session: AsyncSession,
    context: AuthContext,
    view: CollectionAccount,
    confirmation: ReminderConfirmation,
) -> uuid.UUID:
    require_current_confirmation(view, confirmation)
    now = datetime.now(UTC)
    reminder = CollectionReminder(
        tenant_id=context.tenant_id,
        receivable_id=view.id,
        party_id=view.party_id,
        channel="EMAIL",
        template_id="payment_reminder",
        recipient=confirmation.expected_recipient,
        scheduled_at=now,
        status="PENDING",
        native_confirmation={
            "actor": context.actor_id,
            **confirmation.model_dump(mode="json", by_alias=True),
        },
    )
    session.add(reminder)
    await session.flush()
    session.add(
        OutboxEvent(
            tenant_id=context.tenant_id,
            event_type=NATIVE_REMINDER_EVENT,
            aggregate_type="collection_reminder",
            aggregate_id=str(reminder.id),
            payload={},
            correlation_id=str(reminder.id),
            available_at=now,
        )
    )
    return reminder.id

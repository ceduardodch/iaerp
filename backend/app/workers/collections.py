from __future__ import annotations

import asyncio
import html
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.platform import OutboxEvent, Tenant
from app.models.receivables import (
    CollectionPolicy,
    CollectionReminder,
    Receivable,
    ReceivableInstallment,
)
from app.services import crm_integrations
from app.services.receivables import compute_installment_balance
from app.workers.outbox import OutboxMessage

FISCAL_TZ = ZoneInfo("America/Guayaquil")
COLLECTION_REMINDER_DUE_EVENT = "collection.reminder.due"
CONSUMER_NAME = "iaerp.collection-reminders"


def _format_usd(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _render_collection_email(
    *,
    policy: CollectionPolicy,
    company_name: str,
    party_name: str,
    open_amount: Decimal,
    due_date: date,
    as_of: date,
) -> tuple[str, str, str]:
    """Renderiza la plantilla del tenant y una tabla fiscalmente neutra."""
    days_overdue = max(0, (as_of - due_date).days)
    values = {
        "{{empresa}}": company_name,
        "{{cliente}}": party_name,
        "{{saldo}}": _format_usd(open_amount),
        "{{vencimiento}}": due_date.strftime("%d/%m/%Y"),
        "{{dias_atraso}}": str(days_overdue),
        "{{cuenta_bancaria}}": policy.payment_instructions or "Consulte con nuestro equipo.",
    }

    def render(text: str) -> str:
        for token, value in values.items():
            text = text.replace(token, value)
        return text

    subject = render(policy.email_subject)
    body = render(policy.email_body)
    bank = values["{{cuenta_bancaria}}"]
    plain = (
        f"{body}\n\n"
        f"Saldo pendiente: {values['{{saldo}}']}\n"
        f"Fecha de vencimiento: {values['{{vencimiento}}']}\n"
        f"Días de atraso: {values['{{dias_atraso}}']}\n"
        f"Datos para pago: {bank}"
    )
    html_message = (
        f"<p>{html.escape(body).replace(chr(10), '<br>')}</p>"
        "<table style=\"border-collapse:collapse\" cellpadding=\"8\" border=\"1\">"
        "<tr><th align=\"left\">Saldo pendiente</th>"
        f"<td>{html.escape(values['{{saldo}}'])}</td></tr>"
        "<tr><th align=\"left\">Fecha de vencimiento</th>"
        f"<td>{html.escape(values['{{vencimiento}}'])}</td></tr>"
        "<tr><th align=\"left\">Días de atraso</th>"
        f"<td>{html.escape(values['{{dias_atraso}}'])}</td></tr>"
        "<tr><th align=\"left\">Datos para pago</th>"
        f"<td>{html.escape(bank).replace(chr(10), '<br>')}</td></tr>"
        "</table>"
    )
    return subject, plain, html_message


async def schedule_receivable_reminders(
    session: AsyncSession,
    *,
    receivable: Receivable,
    installments: list[ReceivableInstallment],
) -> int:
    policy = await session.get(CollectionPolicy, receivable.tenant_id)
    if policy is None or not policy.enabled:
        return 0
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == receivable.tenant_id,
            Party.id == receivable.party_id,
        )
    )
    if party is None or party.consent_opt_out:
        return 0
    created = 0
    offsets = [int(value) for value in policy.offsets_days.split(",") if value]
    channels = [value for value in policy.channels.split(",") if value]
    for installment in installments:
        for offset in offsets:
            local_datetime = datetime.combine(
                installment.due_date + timedelta(days=offset),
                time(hour=policy.send_hour),
                tzinfo=FISCAL_TZ,
            )
            scheduled_at = local_datetime.astimezone(UTC)
            for channel in channels:
                recipient = party.email if channel == "EMAIL" else party.phone
                status = "PENDING" if recipient else "SKIPPED"
                session.add(
                    CollectionReminder(
                        tenant_id=receivable.tenant_id,
                        party_id=party.id,
                        receivable_id=receivable.id,
                        installment_id=installment.id,
                        channel=channel,
                        template_id=(
                            policy.email_template_id
                            if channel == "EMAIL"
                            else policy.whatsapp_template_id
                        ),
                        recipient=recipient or "missing-contact",
                        status=status,
                        scheduled_at=scheduled_at,
                        error_message=None if recipient else f"Party has no contact for {channel}",
                    )
                )
                created += 1
    await session.flush()
    return created


async def dispatch_due_reminders_once() -> int:
    async with SessionFactory() as session:
        now = datetime.now(UTC)
        reminders = list(
            await session.scalars(
                select(CollectionReminder)
                .where(
                    CollectionReminder.scheduled_at <= now,
                    or_(
                        CollectionReminder.status == "PENDING",
                        (
                            (CollectionReminder.status == "FAILED")
                            & (CollectionReminder.attempts < 3)
                        ),
                        (
                            (CollectionReminder.status == "PROCESSING")
                            & (CollectionReminder.updated_at < now - timedelta(minutes=10))
                        ),
                    ),
                )
                .order_by(CollectionReminder.scheduled_at)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
        )
        for reminder in reminders:
            reminder.status = "PROCESSING"
            reminder.attempts += 1
            session.add(
                OutboxEvent(
                    tenant_id=reminder.tenant_id,
                    event_type=COLLECTION_REMINDER_DUE_EVENT,
                    aggregate_type="collection_reminder",
                    aggregate_id=str(reminder.id),
                    payload={"reminder_id": str(reminder.id)},
                    correlation_id=f"collection-reminder:{reminder.id}:{reminder.attempts}",
                    available_at=now,
                )
            )
        await session.commit()
        return len(reminders)


async def handle_collection_reminder_due(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    try:
        reminder_id = uuid.UUID(message.aggregate_id)
    except ValueError:
        return
    reminder = await session.scalar(
        select(CollectionReminder)
        .where(
            CollectionReminder.id == reminder_id,
            CollectionReminder.tenant_id == message.tenant_id,
        )
        .with_for_update()
    )
    if reminder is None or reminder.status == "SENT":
        return

    integration = await crm_integrations.google_integration_for_tenant(session, reminder.tenant_id)
    context = AuthContext(
        actor_id=str(integration.user_id) if integration else str(uuid.UUID(int=0)),
        actor_type="SYSTEM",
        tenant_id=reminder.tenant_id,
        roles=frozenset({"scheduler"}),
        scopes=frozenset({"communications:write"}),
        token_id="collection-scheduler",
    )
    try:
        if reminder.channel == "EMAIL":
            if integration is None:
                raise RuntimeError("Google Workspace is not connected")
            policy = await session.get(CollectionPolicy, reminder.tenant_id)
            party = await session.scalar(
                select(Party).where(
                    Party.tenant_id == reminder.tenant_id, Party.id == reminder.party_id
                )
            )
            installment = (
                await session.get(ReceivableInstallment, reminder.installment_id)
                if reminder.installment_id
                else None
            )
            if policy is None or party is None or installment is None:
                raise RuntimeError("Collection reminder context is incomplete")
            open_amount = await compute_installment_balance(
                session, tenant_id=reminder.tenant_id, installment=installment
            )
            tenant = await session.get(Tenant, reminder.tenant_id)
            if tenant is None:
                raise RuntimeError("Collection reminder tenant is missing")
            subject, email_text, html_message = _render_collection_email(
                policy=policy,
                company_name=tenant.name,
                party_name=party.name,
                open_amount=open_amount,
                due_date=installment.due_date,
                as_of=datetime.now(FISCAL_TZ).date(),
            )
            await crm_integrations.send_google_email(
                session,
                context,
                recipient=reminder.recipient,
                subject=subject,
                message=email_text,
                html_message=html_message,
            )
        else:
            await crm_integrations.send_whatsapp_message(
                session,
                context,
                recipient=reminder.recipient,
                message="Recordatorio de pago pendiente",
                template_id=reminder.template_id,
                purpose="COLLECTIONS",
            )
    except Exception as exc:
        detail = getattr(exc, "detail", str(exc))
        reminder.status = "FAILED"
        reminder.error_message = str(detail)[:1000]
    else:
        reminder.status = "SENT"
        reminder.sent_at = datetime.now(UTC)
        reminder.error_message = None


async def run_collection_scheduler() -> None:
    while True:
        await dispatch_due_reminders_once()
        await asyncio.sleep(60)

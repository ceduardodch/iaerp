"""Planificador de avisos: decide que eventos deben existir hoy.

Corre en bucle desde ``workers/dispatcher.py``. Su unica responsabilidad es
crear ``NotificationEvent`` con la fecha en que deben salir; no envia nada.

**Es idempotente por diseno.** Corre cada minuto, asi que sin deduplicacion
programaria el mismo aviso 1.440 veces al dia. La garantia es
``uq_notification_events_tenant_dedupe_key``: la clave se arma con datos
estables (tipo, regla, periodo, offset), nunca con la hora de la corrida.

Tampoco decide nada fiscal. Lee ``TaxPeriod`` y ``TaxTask``, que ya son la
verdad del modulo tributario, en vez de recalcular estados por su cuenta: dos
fuentes para el mismo hecho terminan contradiciendose.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory
from app.models.notifications import NotificationEvent, NotificationRule
from app.models.platform import Tenant
from app.models.tax import TaxPeriod, TaxTask
from app.services.notifications import catalog, scheduling
from app.services.tax import due_dates

_OPEN_TASK_STATUSES = ("PENDIENTE", "EN_PROCESO")


async def ensure_default_rules(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    """Crea las reglas que falten para el tenant, siempre apagadas.

    Devuelve cuantas creo. Repetirlo no duplica: solo mira los tipos ausentes.
    """
    existing = set(
        await session.scalars(
            select(NotificationRule.rule_type).where(NotificationRule.tenant_id == tenant_id)
        )
    )
    created = 0
    for rule_type in catalog.IMPLEMENTED_RULE_TYPES:
        if rule_type in existing:
            continue
        definition = catalog.definition_for(rule_type)
        session.add(
            NotificationRule(
                tenant_id=tenant_id,
                rule_type=definition.rule_type,
                name=definition.name,
                enabled=False,
                schedule_kind=definition.schedule_kind,
                days_of_month=definition.days_of_month,
                offsets_days=definition.offsets_days,
                send_hour=definition.send_hour,
                channels="EMAIL",
                audience_kind="TENANT_USERS",
                audience_roles=list(definition.audience_roles),
                audience_emails=[],
                params={},
                require_ack=definition.require_ack,
            )
        )
        created += 1
    if created:
        await session.flush()
    return created


async def _ensure_event(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    dedupe_key: str,
    scheduled_at_day: date,
    payload: dict[str, object],
) -> bool:
    """Crea el evento si no existe. Devuelve ``True`` solo si lo creo.

    El ``SELECT`` previo resuelve el caso normal; el savepoint cubre la carrera
    entre dos planificadores, para que perder esa carrera no tumbe el bucle.
    """
    already_planned = await session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.tenant_id == rule.tenant_id,
            NotificationEvent.dedupe_key == dedupe_key,
        )
    )
    if already_planned is not None:
        return False

    event = NotificationEvent(
        tenant_id=rule.tenant_id,
        rule_id=rule.id,
        rule_type=rule.rule_type,
        dedupe_key=dedupe_key,
        scheduled_at=scheduling.local_send_datetime(
            scheduled_at_day, send_hour=rule.send_hour
        ),
        status="PENDING",
        payload=payload,
    )
    try:
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except IntegrityError:
        return False
    return True


async def _open_task_titles(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    period_id: uuid.UUID,
) -> list[str]:
    titles = await session.scalars(
        select(TaxTask.title).where(
            TaxTask.tenant_id == tenant_id,
            TaxTask.tax_period_id == period_id,
            TaxTask.status.in_(_OPEN_TASK_STATUSES),
        )
    )
    return list(titles)


async def _plan_iva_declaracion(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    tenant: Tenant,
    today: date,
) -> int:
    """Programa los recordatorios de declaracion de IVA que caen hoy."""
    offsets = scheduling.parse_offsets(rule.offsets_days)
    if not offsets:
        return 0

    periods = list(
        await session.scalars(
            select(TaxPeriod).where(
                TaxPeriod.tenant_id == rule.tenant_id,
                TaxPeriod.obligation_type == "IVA",
                TaxPeriod.status != "DECLARADO",
                TaxPeriod.due_date.is_not(None),
            )
        )
    )

    created = 0
    for period in periods:
        due_date = period.due_date
        if due_date is None:  # pragma: no cover - filtrado en la consulta
            continue
        occurrences = scheduling.offset_occurrences(
            due_date=due_date, offsets=offsets, today=today
        )
        if not occurrences:
            continue
        # El calendario de feriados todavia no se carga (P0.3 del plan), asi
        # que esto viene en False y el correo lo advierte en vez de aparentar
        # que la fecha esta verificada.
        computed = due_dates.due_date_for_period(
            obligation_type="IVA",
            year=period.year,
            month=period.month,
            ruc=tenant.ruc,
        )
        open_tasks = await _open_task_titles(
            session, tenant_id=rule.tenant_id, period_id=period.id
        )
        for offset in occurrences:
            payload: dict[str, object] = {
                "period_id": str(period.id),
                "period_label": f"{period.month:02d}/{period.year}",
                "due_date": due_date.isoformat(),
                "days_remaining": (due_date - today).days,
                "period_status": period.status,
                "open_tasks": open_tasks,
                "holidays_checked": computed.holidays_checked if computed else False,
                "offset_days": offset,
            }
            created += await _ensure_event(
                session,
                rule=rule,
                dedupe_key=f"{rule.rule_type}:{rule.id}:{period.id}:{offset:+d}",
                scheduled_at_day=today,
                payload=payload,
            )
    return created


_PLANNERS = {
    "IVA_DECLARACION": _plan_iva_declaracion,
}


async def plan_notifications_for_tenant(
    session: AsyncSession,
    *,
    tenant: Tenant,
    today: date,
) -> int:
    await ensure_default_rules(session, tenant_id=tenant.id)
    rules = list(
        await session.scalars(
            select(NotificationRule).where(
                NotificationRule.tenant_id == tenant.id,
                NotificationRule.enabled.is_(True),
            )
        )
    )
    created = 0
    for rule in rules:
        planner = _PLANNERS.get(rule.rule_type)
        if planner is None:
            continue
        created += await planner(session, rule=rule, tenant=tenant, today=today)
    return created


async def plan_notifications_once(*, today: date | None = None) -> int:
    """Programa los avisos de todos los tenants activos. Devuelve cuantos creo."""
    reference_day = today or today_in_fiscal_timezone()
    async with SessionFactory() as session:
        tenants = list(await session.scalars(select(Tenant).where(Tenant.active.is_(True))))

    created = 0
    for tenant in tenants:
        async with SessionFactory() as session, session.begin():
            refreshed = await session.get(Tenant, tenant.id)
            if refreshed is None:  # pragma: no cover - el tenant se borro en el medio
                continue
            created += await plan_notifications_for_tenant(
                session, tenant=refreshed, today=reference_day
            )
    return created


__all__ = [
    "ensure_default_rules",
    "plan_notifications_for_tenant",
    "plan_notifications_once",
]

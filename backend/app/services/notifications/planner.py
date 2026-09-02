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

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.legal_commercial import PartyBillingSchedule
from app.models.masters import Party
from app.models.notifications import NotificationEvent, NotificationRule
from app.models.payroll import PayrollEntry, PayrollPeriod
from app.models.platform import Tenant
from app.models.tax import FiscalDocument, TaxPeriod, TaxTask
from app.services.notifications import catalog, scheduling
from app.services.tax import due_dates
from app.services.tax.iva import compute_iva

_OPEN_TASK_STATUSES = ("PENDIENTE", "EN_PROCESO")

# Una factura en cualquiera de estos estados ya existe: el recordatorio de
# facturar cumplio su proposito. DRAFT no cuenta (nadie la emitio todavia) ni
# los terminales negativos (hay que rehacerla).
_ISSUED_INVOICE_STATUSES = (
    "READY",
    "SIGNED",
    "RECEIVED",
    "PENDING_AUTHORIZATION",
    "AUTHORIZED",
)
_INVOICE_DOCUMENT_TYPE = "INVOICE"

# Dia limite del aporte al IESS. Parametrizable por regla mas adelante; hoy es
# el 15, corrido al siguiente dia habil.
_IESS_DUE_DAY = 15

_MONTHS_BY_FREQUENCY = {"MONTHLY": 1, "BIMONTHLY": 2, "QUARTERLY": 3, "ANNUAL": 12}


def _scheduler_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        actor_id="notification-scheduler",
        actor_type="SYSTEM",
        tenant_id=tenant_id,
        roles=frozenset({"scheduler"}),
        scopes=frozenset({"tax:read"}),
        token_id="notification-scheduler",
    )


def _month_bounds(*, year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _previous_month(day: date) -> tuple[int, int]:
    return (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)


def _next_month(*, year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


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


def _billing_month_matches(schedule: PartyBillingSchedule, *, year: int, month: int) -> bool:
    """Si el ciclo del cliente cae en ese mes.

    Un ciclo no mensual sin ``anchor_month`` no se programa: la base ya lo
    impide, pero adivinar el mes de arranque pondria el aviso en el mes
    equivocado, que es peor que no mandarlo.
    """
    interval = _MONTHS_BY_FREQUENCY.get(schedule.frequency)
    if interval is None:  # pragma: no cover - el CHECK ya restringe el valor
        return False
    if interval == 1:
        return True
    if schedule.anchor_month is None:
        return False
    return (month - schedule.anchor_month) % interval == 0


async def _already_invoiced(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID,
    year: int,
    month: int,
) -> bool:
    start, end = _month_bounds(year=year, month=month)
    found = await session.scalar(
        select(SalesDocument.id).where(
            SalesDocument.tenant_id == tenant_id,
            SalesDocument.party_id == party_id,
            SalesDocument.document_type == _INVOICE_DOCUMENT_TYPE,
            SalesDocument.status.in_(_ISSUED_INVOICE_STATUSES),
            SalesDocument.archived_at.is_(None),
            SalesDocument.issue_date >= start,
            SalesDocument.issue_date <= end,
        )
    )
    return found is not None


async def _plan_cliente_facturar(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    tenant: Tenant,
    today: date,
) -> int:
    """Avisa que a un cliente le toca factura y todavia no la tiene."""
    del tenant
    offsets = scheduling.parse_offsets(rule.offsets_days) or [0]
    schedules = list(
        await session.scalars(
            select(PartyBillingSchedule).where(
                PartyBillingSchedule.tenant_id == rule.tenant_id,
                PartyBillingSchedule.active.is_(True),
            )
        )
    )

    created = 0
    for schedule in schedules:
        # El dia de facturacion mas el recordatorio de seguimiento puede caer
        # en el mes siguiente (un ciclo el 31 con offset +2), asi que se miran
        # tambien los ciclos del mes anterior.
        candidate_months = [(today.year, today.month), _previous_month(today)]
        for year, month in candidate_months:
            if not _billing_month_matches(schedule, year=year, month=month):
                continue
            billing_day = scheduling.clamp_day_of_month(
                year=year, month=month, day=schedule.day_of_month
            )
            matching = [
                offset for offset in offsets if billing_day + timedelta(days=offset) == today
            ]
            if not matching:
                continue
            if await _already_invoiced(
                session,
                tenant_id=rule.tenant_id,
                party_id=schedule.party_id,
                year=year,
                month=month,
            ):
                continue
            party = await session.scalar(
                select(Party).where(
                    Party.tenant_id == rule.tenant_id,
                    Party.id == schedule.party_id,
                )
            )
            if party is None:  # pragma: no cover - la FK lo impide
                continue
            for offset in matching:
                payload: dict[str, object] = {
                    "schedule_id": str(schedule.id),
                    "party_id": str(schedule.party_id),
                    "party_name": party.name,
                    "period_label": f"{month:02d}/{year}",
                    "period_year": year,
                    "period_month": month,
                    "billing_day": schedule.day_of_month,
                    "frequency": schedule.frequency,
                    "amount_hint": (
                        str(schedule.amount_hint) if schedule.amount_hint is not None else None
                    ),
                    "notes": schedule.notes,
                    "offset_days": offset,
                }
                created += await _ensure_event(
                    session,
                    rule=rule,
                    dedupe_key=(
                        f"{rule.rule_type}:{rule.id}:{schedule.id}:"
                        f"{year}-{month:02d}:{offset:+d}"
                    ),
                    scheduled_at_day=today,
                    payload=payload,
                )
    return created


async def _has_acknowledged_sibling(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    dedupe_prefix: str,
) -> bool:
    """Si ya hubo un acuse humano para el mismo asunto.

    Los offsets de un mismo periodo comparten prefijo de clave; cuando una
    persona confirma que ya pago, los recordatorios siguientes sobran.
    """
    found = await session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.tenant_id == tenant_id,
            NotificationEvent.dedupe_key.startswith(dedupe_prefix),
            NotificationEvent.ack_at.is_not(None),
        )
    )
    return found is not None


async def _plan_iess_aporte(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    tenant: Tenant,
    today: date,
) -> int:
    del tenant
    offsets = scheduling.parse_offsets(rule.offsets_days)
    if not offsets:
        return 0

    periods = list(
        await session.scalars(
            select(PayrollPeriod).where(PayrollPeriod.tenant_id == rule.tenant_id)
        )
    )

    created = 0
    for period in periods:
        due_year, due_month = _next_month(year=period.anio, month=period.mes)
        due_date = due_dates.next_business_day(date(due_year, due_month, _IESS_DUE_DAY))
        occurrences = scheduling.offset_occurrences(
            due_date=due_date, offsets=offsets, today=today
        )
        if not occurrences:
            continue

        totals = (
            await session.execute(
                select(
                    func.coalesce(func.sum(PayrollEntry.aporte_iess), 0),
                    func.count(PayrollEntry.id),
                ).where(
                    PayrollEntry.tenant_id == rule.tenant_id,
                    PayrollEntry.period_id == period.id,
                )
            )
        ).one()
        aporte_personal, employee_count = Decimal(str(totals[0])), int(totals[1])
        if employee_count == 0:
            # Un rol sin empleados no genera planilla; no hay nada que avisar.
            continue

        dedupe_prefix = f"{rule.rule_type}:{rule.id}:{period.id}:"
        if await _has_acknowledged_sibling(
            session, tenant_id=rule.tenant_id, dedupe_prefix=dedupe_prefix
        ):
            continue

        for offset in occurrences:
            payload: dict[str, object] = {
                "payroll_period_id": str(period.id),
                "period_label": f"{period.mes:02d}/{period.anio}",
                "due_date": due_date.isoformat(),
                "days_remaining": (due_date - today).days,
                "employee_count": employee_count,
                "aporte_personal": str(aporte_personal),
                "payroll_status": period.status,
                "holidays_checked": False,
                "offset_days": offset,
            }
            created += await _ensure_event(
                session,
                rule=rule,
                dedupe_key=f"{dedupe_prefix}{offset:+d}",
                scheduled_at_day=today,
                payload=payload,
            )
    return created


async def _plan_resumen_mensual(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    tenant: Tenant,
    today: date,
) -> int:
    """Resumen del mes cerrado, en los primeros dias del siguiente."""
    del tenant
    days = scheduling.parse_days_of_month(rule.days_of_month)
    if not scheduling.day_of_month_occurs(days=days, today=today):
        return 0

    year, month = _previous_month(today)
    start, end = _month_bounds(year=year, month=month)

    sales = (
        await session.execute(
            select(
                func.coalesce(func.sum(SalesDocument.total), 0),
                func.count(SalesDocument.id),
            ).where(
                SalesDocument.tenant_id == rule.tenant_id,
                SalesDocument.document_type == _INVOICE_DOCUMENT_TYPE,
                SalesDocument.status.in_(_ISSUED_INVOICE_STATUSES),
                SalesDocument.archived_at.is_(None),
                SalesDocument.issue_date >= start,
                SalesDocument.issue_date <= end,
            )
        )
    ).one()

    purchases = (
        await session.execute(
            select(
                func.coalesce(func.sum(FiscalDocument.total), 0),
                func.count(FiscalDocument.id),
                func.coalesce(func.sum(func.cast(FiscalDocument.is_preliminary, Integer)), 0),
            ).where(
                FiscalDocument.tenant_id == rule.tenant_id,
                FiscalDocument.direction == "RECIBIDO",
                FiscalDocument.doc_type != "RETENCION",
                FiscalDocument.issue_date >= start,
                FiscalDocument.issue_date <= end,
            )
        )
    ).one()

    income = Decimal(str(sales[0]))
    expense = Decimal(str(purchases[0]))
    payload: dict[str, object] = {
        "period_label": f"{month:02d}/{year}",
        "period_year": year,
        "period_month": month,
        "income_total": str(income),
        "income_count": int(sales[1]),
        "expense_total": str(expense),
        "expense_count": int(purchases[1]),
        "result_total": str(income - expense),
        "preliminary_purchase_count": int(purchases[2]),
    }
    return await _ensure_event(
        session,
        rule=rule,
        dedupe_key=f"{rule.rule_type}:{rule.id}:{year}-{month:02d}:d{today.day}",
        scheduled_at_day=today,
        payload=payload,
    )


async def _plan_iva_preview(
    session: AsyncSession,
    *,
    rule: NotificationRule,
    tenant: Tenant,
    today: date,
) -> int:
    """Avance del IVA del mes en curso, el ultimo dia habil."""
    del tenant
    if today != scheduling.last_business_day(year=today.year, month=today.month):
        return 0

    period = await session.scalar(
        select(TaxPeriod).where(
            TaxPeriod.tenant_id == rule.tenant_id,
            TaxPeriod.year == today.year,
            TaxPeriod.month == today.month,
            TaxPeriod.obligation_type == "IVA",
        )
    )
    if period is None:
        # Sin periodo abierto no hay evidencia que resumir. El aviso de
        # evidencia incompleta es el que cubre ese caso, no este.
        return 0

    summary = await compute_iva(session, _scheduler_context(rule.tenant_id), period=period)
    payload: dict[str, object] = {
        "period_id": str(period.id),
        "period_label": f"{period.month:02d}/{period.year}",
        "iva_generado": str(summary.value("iva_generado")),
        "credito_tributario": str(summary.value("iva_credito_tributario")),
        "saldo_a_pagar": str(summary.value("saldo_a_pagar")),
        "document_count": summary.document_count,
        "is_preliminary": summary.is_preliminary,
        "preliminary_reasons": list(summary.preliminary_reasons),
    }
    return await _ensure_event(
        session,
        rule=rule,
        dedupe_key=f"{rule.rule_type}:{rule.id}:{period.id}:{today.isoformat()}",
        scheduled_at_day=today,
        payload=payload,
    )


_PLANNERS = {
    "IVA_DECLARACION": _plan_iva_declaracion,
    "CLIENTE_FACTURAR": _plan_cliente_facturar,
    "IESS_APORTE": _plan_iess_aporte,
    "RESUMEN_MENSUAL": _plan_resumen_mensual,
    "IVA_PREVIEW_MENSUAL": _plan_iva_preview,
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

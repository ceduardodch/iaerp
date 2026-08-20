"""Bandeja de acción: candidatos a WhatsApp de cobranza y prospección (solo lectura).

Agrega dos flujos que ya existen por separado -- recordatorios de cobranza
(``services/receivables.py::send_real_reminder``) y mensajes de primer
contacto de leads (``POST /crm/leads/{lead_id}/messages``, ver
``api/crm.py::post_lead_message``) -- en una sola lista para que el dueño del
negocio revise y dispare el envío desde un solo lugar, en vez de entrar
factura por factura o lead por lead.

Este módulo NUNCA envía nada: solo lee y sugiere un texto. El botón "Enviar"
del frontend sigue llamando a los dos endpoints de envío que ya existen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.models.crm import Lead, LeadActivity
from app.models.masters import Party
from app.models.receivables import CollectionReminder, Receivable
from app.services import receivables
from app.services.collection_email import format_usd

DEFAULT_COOLDOWN_DAYS = 5
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Un recordatorio en cualquiera de estos estados cuenta como "ya en curso":
# no tiene sentido sugerir otro mientras este no falle ni se salte
# (``FAILED``/``SKIPPED`` sí liberan al candidato).
_ACTIVE_REMINDER_STATUSES = ("PENDING", "PROCESSING", "SENT")
_CLOSED_LEAD_STATUSES = ("WON", "LOST")
_OUTREACH_ACTIVITY_TYPES = ("WHATSAPP", "EMAIL")


@dataclass(frozen=True)
class CollectionCandidate:
    receivable_id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    phone: str
    open_amount: Decimal
    days_overdue: int
    last_reminder_at: datetime | None
    suggested_message: str


@dataclass(frozen=True)
class ProspectingCandidate:
    lead_id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    phone: str
    created_at: datetime
    last_activity_at: datetime | None
    suggested_message: str


@dataclass(frozen=True)
class ActionQueue:
    collections: list[CollectionCandidate]
    prospecting: list[ProspectingCandidate]


def _suggest_collection_message(
    *, party_name: str, open_amount: Decimal, days_overdue: int
) -> str:
    """Mensaje corto de cobranza con el saldo y los días de atraso reales.

    Nunca inventa un monto: usa el mismo saldo que ``compute_receivable_balance``
    ya calcula para la cartera (via ``to_receivable_summary``), para que este
    texto sugerido nunca contradiga lo que el dueño del negocio ve en el
    detalle del receivable.
    """
    return (
        f"Hola {party_name}, le recordamos que mantiene un saldo pendiente de "
        f"{format_usd(open_amount)} con {days_overdue} día(s) de atraso. "
        "¿Podría confirmarnos cuándo podría realizar el pago? Quedamos atentos."
    )


def _suggest_prospecting_message(*, party_name: str, lead_title: str) -> str:
    """Mensaje de bienvenida genérico; no inventa datos que el lead no dio."""
    return (
        f'Hola {party_name}, gracias por tu interés en "{lead_title}". '
        "Soy parte del equipo comercial y me gustaría conversar contigo para "
        "resolver tus dudas. ¿Tienes unos minutos esta semana?"
    )


def _as_utc(value: datetime | None) -> datetime | None:
    """Normaliza un timestamp leído de la base a ``UTC`` aware.

    ``DateTime(timezone=True)`` en SQLite (usado por la suite de pruebas) no
    conserva el offset: la fila vuelve naive aunque se guardó en UTC. Sin esto,
    compararla contra un ``cutoff`` aware (``datetime.now(UTC)``) revienta con
    ``TypeError`` solo en SQLite, nunca en PostgreSQL. Mismo patrón que
    ``services/automation_rate.py``/``services/crm_integrations.py``.
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def _last_reminder_at(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> datetime | None:
    value = await session.scalar(
        select(CollectionReminder.created_at)
        .where(
            CollectionReminder.tenant_id == tenant_id,
            CollectionReminder.receivable_id == receivable_id,
        )
        .order_by(CollectionReminder.created_at.desc())
        .limit(1)
    )
    return _as_utc(value)


async def _has_recent_active_reminder(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    receivable_id: uuid.UUID,
    cutoff: datetime,
) -> bool:
    recent = await session.scalar(
        select(CollectionReminder.id)
        .where(
            CollectionReminder.tenant_id == tenant_id,
            CollectionReminder.receivable_id == receivable_id,
            CollectionReminder.status.in_(_ACTIVE_REMINDER_STATUSES),
            CollectionReminder.created_at >= cutoff,
        )
        .limit(1)
    )
    return recent is not None


async def _list_collection_candidates(
    session: AsyncSession,
    context: AuthContext,
    *,
    cooldown_days: int,
    limit: int,
) -> list[CollectionCandidate]:
    tenant_id = context.tenant_id
    as_of = today_in_fiscal_timezone()
    cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)

    stmt = (
        select(Receivable, Party)
        .join(Party, Party.id == Receivable.party_id)
        .where(
            Receivable.tenant_id == tenant_id,
            Receivable.status.in_(("OPEN", "PARTIALLY_PAID")),
            Receivable.collection_enabled.is_(True),
            Party.consent_opt_out.is_(False),
            Party.phone.is_not(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    candidates: list[CollectionCandidate] = []
    for receivable, party in rows:
        summary = await receivables.to_receivable_summary(
            session, tenant_id=tenant_id, receivable=receivable, as_of=as_of
        )
        # Solo candidatos realmente vencidos (invariante 13: OVERDUE es
        # derivado, nunca persistido en ``Receivable.status``). Una cuenta
        # OPEN que todavía no llegó a su vencimiento no necesita recordatorio.
        if summary.status != "OVERDUE" or summary.aging_days_overdue is None:
            continue
        if await _has_recent_active_reminder(
            session, tenant_id=tenant_id, receivable_id=receivable.id, cutoff=cutoff
        ):
            continue
        last_reminder_at = await _last_reminder_at(
            session, tenant_id=tenant_id, receivable_id=receivable.id
        )
        assert party.phone is not None  # filtrado por la consulta de arriba
        candidates.append(
            CollectionCandidate(
                receivable_id=receivable.id,
                party_id=party.id,
                party_name=party.name,
                phone=party.phone,
                open_amount=summary.open_amount,
                days_overdue=summary.aging_days_overdue,
                last_reminder_at=last_reminder_at,
                suggested_message=_suggest_collection_message(
                    party_name=party.name,
                    open_amount=summary.open_amount,
                    days_overdue=summary.aging_days_overdue,
                ),
            )
        )

    candidates.sort(key=lambda item: item.days_overdue, reverse=True)
    return candidates[:limit]


async def _last_outreach_activity_at(
    session: AsyncSession, *, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> datetime | None:
    value = await session.scalar(
        select(LeadActivity.created_at)
        .where(
            LeadActivity.tenant_id == tenant_id,
            LeadActivity.lead_id == lead_id,
            LeadActivity.activity_type.in_(_OUTREACH_ACTIVITY_TYPES),
        )
        .order_by(LeadActivity.created_at.desc())
        .limit(1)
    )
    return _as_utc(value)


async def _list_prospecting_candidates(
    session: AsyncSession,
    context: AuthContext,
    *,
    cooldown_days: int,
    limit: int,
) -> list[ProspectingCandidate]:
    tenant_id = context.tenant_id
    cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)

    # Mismo patrón de join que ``services/crm.py::capture_campaign_lead`` usa
    # para filtrar leads por datos de su ``Party``.
    stmt = (
        select(Lead)
        .join(Party, Party.id == Lead.party_id)
        .where(
            Lead.tenant_id == tenant_id,
            Lead.status.not_in(_CLOSED_LEAD_STATUSES),
            Party.consent_opt_out.is_(False),
            Party.phone.is_not(None),
        )
        .order_by(Lead.created_at.asc(), Lead.id.asc())
    )
    leads = list((await session.scalars(stmt)).all())

    candidates: list[ProspectingCandidate] = []
    for lead in leads:
        if len(candidates) >= limit:
            break
        last_activity_at = await _last_outreach_activity_at(
            session, tenant_id=tenant_id, lead_id=lead.id
        )
        if last_activity_at is not None and last_activity_at >= cutoff:
            continue
        party = lead.party
        assert party.phone is not None  # filtrado por la consulta de arriba
        candidates.append(
            ProspectingCandidate(
                lead_id=lead.id,
                party_id=party.id,
                party_name=party.name,
                phone=party.phone,
                created_at=lead.created_at,
                last_activity_at=last_activity_at,
                suggested_message=_suggest_prospecting_message(
                    party_name=party.name, lead_title=lead.title
                ),
            )
        )

    return candidates


async def build_action_queue(
    session: AsyncSession,
    context: AuthContext,
    *,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> ActionQueue:
    """Arma la bandeja única de candidatos a WhatsApp del tenant activo.

    Solo lectura: no crea ``CollectionReminder`` ni ``LeadActivity``. El envío
    real sigue pasando por los endpoints ya existentes
    (``POST /receivables/{id}/reminders`` y ``POST /crm/leads/{id}/messages``);
    este módulo solo decide qué mostrar y con qué texto sugerido.

    ``cooldown_days`` evita repetir el mismo mensaje a un cliente/lead que ya
    recibió uno recientemente (por defecto 5 días, igual para ambas listas).
    ``limit`` topea cada lista por separado (por defecto 50, máximo 200).
    """
    bounded_limit = min(max(limit, 1), MAX_LIMIT)
    collections = await _list_collection_candidates(
        session, context, cooldown_days=cooldown_days, limit=bounded_limit
    )
    prospecting = await _list_prospecting_candidates(
        session, context, cooldown_days=cooldown_days, limit=bounded_limit
    )
    return ActionQueue(collections=collections, prospecting=prospecting)


__all__ = [
    "ActionQueue",
    "CollectionCandidate",
    "ProspectingCandidate",
    "build_action_queue",
]

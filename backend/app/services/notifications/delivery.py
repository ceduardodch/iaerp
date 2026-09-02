"""Resuelve destinatarios, arma el correo y lo entrega.

Separado del planificador porque son dos decisiones distintas: *cuando* avisar
(planner) y *que decir y a quien* (aqui). Un cambio de plantilla no deberia
poder alterar el calendario, ni al reves.

La regla de contenido que gobierna este modulo: **una cifra o una fecha sin
verificar se anuncia como tal**. El aviso de declaracion lleva la advertencia
de feriados mientras nadie cargue el calendario, en vez de mostrar una fecha
que aparente estar confirmada.
"""

from __future__ import annotations

import html
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.notifications.email_sender import EmailMessage, EmailSender
from app.models.notifications import (
    NotificationDelivery,
    NotificationEvent,
    NotificationRule,
    NotificationTemplate,
)
from app.models.platform import Membership, Tenant, User
from app.models.tax import TaxPeriod
from app.services.notifications import catalog, scheduling

_PERIOD_STATUS_LABELS = {
    "PENDIENTE_DESCARGA": "Pendiente de bajar comprobantes",
    "EVIDENCIA_INCOMPLETA": "Evidencia incompleta",
    "LISTO_REVISAR": "Listo para revisar",
    "LISTO_DECLARAR": "Listo para declarar",
    "DECLARADO": "Declarado",
}

_HOLIDAYS_WARNING = (
    "Verifica si la fecha cae en feriado: IAERP corre la fecha por fines de "
    "semana, pero todavia no tiene cargado el calendario de feriados."
)


async def resolve_recipients(session: AsyncSession, *, rule: NotificationRule) -> list[str]:
    """Correos a los que va este aviso, sin repetidos y en orden estable.

    ``TENANT_USERS`` con ``audience_roles`` vacio significa "todos los miembros
    activos": es el default util para una empresa pequena, donde exigir que
    alguien configure roles antes de recibir nada solo estorba.
    """
    if rule.audience_kind == "EXPLICIT_EMAILS":
        return sorted({email.strip() for email in rule.audience_emails if email.strip()})

    if rule.audience_kind != "TENANT_USERS":
        # PARTY queda declarado en el esquema pero no lo usa ningun aviso
        # interno; devolver vacio hace que el evento quede SKIPPED con motivo.
        return []

    rows = list(
        await session.execute(
            select(User.email, Membership.roles)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == rule.tenant_id,
                Membership.active.is_(True),
                User.active.is_(True),
            )
        )
    )
    wanted_roles = {role for role in rule.audience_roles if role}
    recipients = {
        email
        for email, roles in rows
        if not wanted_roles or wanted_roles.intersection(roles or [])
    }
    return sorted(recipients)


async def template_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    rule_type: str,
) -> tuple[str, str]:
    """Asunto y cuerpo del tenant, o el default del catalogo si no hay fila."""
    override = await session.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.tenant_id == tenant_id,
            NotificationTemplate.rule_type == rule_type,
        )
    )
    if override is not None:
        return override.subject, override.body
    definition = catalog.definition_for(rule_type)
    return definition.subject, definition.body


def _format_due_date(raw: object) -> str:
    if not isinstance(raw, str):
        return "sin fecha"
    try:
        return date.fromisoformat(raw).strftime("%d/%m/%Y")
    except ValueError:
        return "sin fecha"


def _format_open_tasks(raw: object) -> str:
    if not isinstance(raw, list) or not raw:
        return "Sin pendientes registrados para el periodo."
    titles = [str(item) for item in raw]
    return "Pendientes abiertos:\n" + "\n".join(f"- {title}" for title in titles)


def placeholder_values(*, company_name: str, payload: dict[str, object]) -> dict[str, str]:
    """Valores de los marcadores a partir del snapshot guardado en el evento.

    Se lee del ``payload`` y no de la base para que el correo diga exactamente
    lo que se calculo al programar el aviso.
    """
    days_remaining = payload.get("days_remaining")
    status = payload.get("period_status")
    return {
        "{{empresa}}": company_name,
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{fecha_limite}}": _format_due_date(payload.get("due_date")),
        "{{dias_restantes}}": (
            scheduling.describe_days_remaining(days_remaining)
            if isinstance(days_remaining, int)
            else "sin fecha"
        ),
        "{{estado}}": _PERIOD_STATUS_LABELS.get(str(status), str(status or "desconocido")),
        "{{pendientes}}": _format_open_tasks(payload.get("open_tasks")),
        "{{aviso_feriados}}": ("" if payload.get("holidays_checked") else _HOLIDAYS_WARNING),
    }


def render(
    *,
    subject_template: str,
    body_template: str,
    values: dict[str, str],
) -> tuple[str, str, str]:
    """Devuelve ``(asunto, texto plano, html)``."""

    def apply(text: str) -> str:
        for token, value in values.items():
            text = text.replace(token, value)
        return text

    subject = apply(subject_template)
    body = apply(body_template)
    # Una linea en blanco de mas cuando un marcador queda vacio (por ejemplo
    # sin advertencia de feriados) se ve como descuido; se colapsan.
    plain = "\n".join(line for line in body.splitlines() if line.strip() or line == "")
    while "\n\n\n" in plain:
        plain = plain.replace("\n\n\n", "\n\n")
    html_body = "<p>{}</p>".format(html.escape(plain).replace("\n", "<br>"))
    return subject, plain, html_body


async def _should_skip(session: AsyncSession, *, event: NotificationEvent) -> str | None:
    """Motivo por el que el aviso ya no corresponde, o ``None`` si sigue vigente.

    Se vuelve a comprobar al entregar y no solo al programar: entre ambos
    momentos pueden pasar dias, y avisar de una declaracion ya presentada es
    justo lo que hace que la gente ignore el resto de los avisos.
    """
    if event.rule_type != "IVA_DECLARACION":
        return None
    raw_period_id = event.payload.get("period_id")
    if not isinstance(raw_period_id, str):
        return None
    period = await session.scalar(
        select(TaxPeriod).where(
            TaxPeriod.tenant_id == event.tenant_id,
            TaxPeriod.id == uuid.UUID(raw_period_id),
        )
    )
    if period is None:
        return "El periodo ya no existe"
    if period.status == "DECLARADO":
        return "El periodo ya fue declarado"
    return None


async def deliver_event(
    session: AsyncSession,
    *,
    event: NotificationEvent,
    sender: EmailSender,
) -> str:
    """Entrega el aviso y deja el evento en su estado final.

    Devuelve el estado resultante. No lanza por un fallo del proveedor: un
    destinatario con el correo mal escrito no debe impedir que el resto reciba
    el aviso.
    """
    skip_reason = await _should_skip(session, event=event)
    if skip_reason is not None:
        event.status = "SKIPPED"
        event.error_message = skip_reason
        return event.status

    rule = await session.scalar(
        select(NotificationRule).where(
            NotificationRule.tenant_id == event.tenant_id,
            NotificationRule.id == event.rule_id,
        )
    )
    if rule is None or not rule.enabled:
        event.status = "SKIPPED"
        event.error_message = "La regla fue desactivada o eliminada"
        return event.status

    recipients = await resolve_recipients(session, rule=rule)
    if not recipients:
        event.status = "SKIPPED"
        event.error_message = "La regla no tiene destinatarios"
        return event.status

    tenant = await session.get(Tenant, event.tenant_id)
    subject_template, body_template = await template_for(
        session, tenant_id=event.tenant_id, rule_type=event.rule_type
    )
    subject, plain, html_body = render(
        subject_template=subject_template,
        body_template=body_template,
        values=placeholder_values(
            company_name=tenant.name if tenant is not None else "",
            payload=event.payload,
        ),
    )

    statuses: list[str] = []
    for recipient in recipients:
        result = await sender.send(
            EmailMessage(
                recipient=recipient,
                subject=subject,
                body_text=plain,
                body_html=html_body,
            )
        )
        statuses.append(result.status)
        existing = await session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.tenant_id == event.tenant_id,
                NotificationDelivery.event_id == event.id,
                NotificationDelivery.recipient == recipient,
            )
        )
        delivery = existing or NotificationDelivery(
            tenant_id=event.tenant_id,
            event_id=event.id,
            recipient=recipient,
        )
        delivery.channel = "EMAIL"
        delivery.provider = result.provider
        delivery.provider_message_id = result.provider_message_id
        delivery.status = result.status
        delivery.error_message = result.error_message
        delivery.sent_at = datetime.now(UTC) if result.status != "FAILED" else None
        if existing is None:
            session.add(delivery)

    if "SENT" in statuses:
        event.status = "SENT"
    elif "STUBBED" in statuses:
        event.status = "STUBBED"
    else:
        event.status = "FAILED"
    event.sent_at = datetime.now(UTC)
    event.error_message = None if event.status != "FAILED" else "Ningun envio prospero"
    await session.flush()
    return event.status


__all__ = [
    "deliver_event",
    "placeholder_values",
    "render",
    "resolve_recipients",
    "template_for",
]

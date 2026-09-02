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

import calendar
import html
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.notifications.email_sender import EmailMessage, EmailSender
from app.models.billing import SalesDocument
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


def _format_usd(raw: object) -> str:
    if raw is None:
        return "sin dato"
    try:
        return f"${Decimal(str(raw)):,.2f}"
    except (InvalidOperation, ValueError):
        return "sin dato"


def _days_remaining_text(payload: dict[str, object]) -> str:
    days_remaining = payload.get("days_remaining")
    if isinstance(days_remaining, int):
        return scheduling.describe_days_remaining(days_remaining)
    return "sin fecha"


def _holidays_notice(payload: dict[str, object]) -> str:
    return "" if payload.get("holidays_checked") else _HOLIDAYS_WARNING


def _iva_declaracion_values(payload: dict[str, object]) -> dict[str, str]:
    status = payload.get("period_status")
    return {
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{fecha_limite}}": _format_due_date(payload.get("due_date")),
        "{{dias_restantes}}": _days_remaining_text(payload),
        "{{estado}}": _PERIOD_STATUS_LABELS.get(str(status), str(status or "desconocido")),
        "{{pendientes}}": _format_open_tasks(payload.get("open_tasks")),
        "{{aviso_feriados}}": _holidays_notice(payload),
    }


def _cliente_facturar_values(payload: dict[str, object]) -> dict[str, str]:
    amount_hint = payload.get("amount_hint")
    notes = payload.get("notes")
    return {
        "{{cliente}}": str(payload.get("party_name", "")),
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{dia}}": str(payload.get("billing_day", "")),
        "{{monto_referencia}}": (
            f"Monto de referencia del calendario: {_format_usd(amount_hint)} "
            "(referencia, no un valor a facturar)."
            if amount_hint is not None
            else "El calendario no tiene monto de referencia."
        ),
        "{{nota}}": str(notes) if notes else "",
    }


def _iess_values(payload: dict[str, object]) -> dict[str, str]:
    return {
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{fecha_limite}}": _format_due_date(payload.get("due_date")),
        "{{dias_restantes}}": _days_remaining_text(payload),
        "{{empleados}}": str(payload.get("employee_count", 0)),
        "{{aporte_personal}}": _format_usd(payload.get("aporte_personal")),
        # Sin esta linea alguien leeria el aporte personal como el total de la
        # planilla y pagaria de menos: el patronal (11,15%) no esta en el rol.
        "{{aviso_patronal}}": (
            "Este monto es solo el aporte personal retenido al trabajador "
            "(9,45%). NO incluye el aporte patronal ni otros rubros de la "
            "planilla: el total a pagar sale del IESS, no de IAERP."
        ),
        "{{aviso_feriados}}": _holidays_notice(payload),
    }


def _resumen_values(payload: dict[str, object]) -> dict[str, str]:
    preliminary = payload.get("preliminary_purchase_count")
    preliminary_count = preliminary if isinstance(preliminary, int) else 0
    return {
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{ingresos}}": _format_usd(payload.get("income_total")),
        "{{egresos}}": _format_usd(payload.get("expense_total")),
        "{{resultado}}": _format_usd(payload.get("result_total")),
        "{{documentos}}": (
            f"Sale de {payload.get('income_count', 0)} factura(s) emitida(s) y "
            f"{payload.get('expense_count', 0)} comprobante(s) de compra."
        ),
        "{{aviso_preliminar}}": (
            f"Ojo: {preliminary_count} comprobante(s) de compra estan "
            "preliminares, asi que el egreso puede subir cuando se complete "
            "su respaldo."
            if preliminary_count
            else ""
        ),
    }


def _iva_preview_values(payload: dict[str, object]) -> dict[str, str]:
    reasons = payload.get("preliminary_reasons")
    reason_lines = (
        "\n".join(f"- {reason}" for reason in reasons)
        if isinstance(reasons, list) and reasons
        else ""
    )
    # Regla de contenido del modulo: con evidencia incompleta no se muestra una
    # cifra que parezca definitiva.
    if payload.get("is_preliminary"):
        warning = "Cifras INCOMPLETAS. Falta evidencia:\n" + (
            reason_lines or "- Hay comprobantes sin respaldo completo."
        )
    else:
        warning = ""
    return {
        "{{periodo}}": str(payload.get("period_label", "")),
        "{{iva_generado}}": _format_usd(payload.get("iva_generado")),
        "{{credito_tributario}}": _format_usd(payload.get("credito_tributario")),
        "{{saldo}}": _format_usd(payload.get("saldo_a_pagar")),
        "{{documentos}}": (
            f"Calculado sobre {payload.get('document_count', 0)} comprobante(s) del periodo."
        ),
        "{{aviso_preliminar}}": warning,
    }


_VALUE_BUILDERS: dict[str, Callable[[dict[str, object]], dict[str, str]]] = {
    "IVA_DECLARACION": _iva_declaracion_values,
    "CLIENTE_FACTURAR": _cliente_facturar_values,
    "IESS_APORTE": _iess_values,
    "RESUMEN_MENSUAL": _resumen_values,
    "IVA_PREVIEW_MENSUAL": _iva_preview_values,
}


def placeholder_values(
    *,
    rule_type: str,
    company_name: str,
    payload: dict[str, object],
) -> dict[str, str]:
    """Valores de los marcadores a partir del snapshot guardado en el evento.

    Se lee del ``payload`` y no de la base para que el correo diga exactamente
    lo que se calculo al programar el aviso, aunque el mundo haya cambiado
    entre medias.
    """
    builder = _VALUE_BUILDERS.get(rule_type)
    values: dict[str, str] = {"{{empresa}}": company_name}
    if builder is not None:
        values.update(builder(payload))
    return values


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


async def _skip_iva_declaracion(
    session: AsyncSession, *, event: NotificationEvent
) -> str | None:
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


async def _skip_cliente_facturar(
    session: AsyncSession, *, event: NotificationEvent
) -> str | None:
    """Si la factura se emitio entre programar y entregar, ya no hay que avisar."""
    raw_party_id = event.payload.get("party_id")
    year = event.payload.get("period_year")
    month = event.payload.get("period_month")
    if not isinstance(raw_party_id, str) or not isinstance(year, int):
        return None
    if not isinstance(month, int):
        return None
    last_day = calendar.monthrange(year, month)[1]
    found = await session.scalar(
        select(SalesDocument.id).where(
            SalesDocument.tenant_id == event.tenant_id,
            SalesDocument.party_id == uuid.UUID(raw_party_id),
            SalesDocument.document_type == "INVOICE",
            SalesDocument.status.in_(
                ("READY", "SIGNED", "RECEIVED", "PENDING_AUTHORIZATION", "AUTHORIZED")
            ),
            SalesDocument.archived_at.is_(None),
            SalesDocument.issue_date >= date(year, month, 1),
            SalesDocument.issue_date <= date(year, month, last_day),
        )
    )
    return "El cliente ya tiene factura del periodo" if found is not None else None


async def _skip_iess_aporte(session: AsyncSession, *, event: NotificationEvent) -> str | None:
    """Un acuse humano cierra el asunto para los recordatorios que faltaban."""
    prefix = event.dedupe_key.rsplit(":", 1)[0] + ":"
    acknowledged = await session.scalar(
        select(NotificationEvent.id).where(
            NotificationEvent.tenant_id == event.tenant_id,
            NotificationEvent.dedupe_key.startswith(prefix),
            NotificationEvent.ack_at.is_not(None),
        )
    )
    return "Ya hay un acuse humano para este periodo" if acknowledged is not None else None


_SKIP_CHECKS: dict[
    str,
    Callable[..., Coroutine[object, object, str | None]],
] = {
    "IVA_DECLARACION": _skip_iva_declaracion,
    "CLIENTE_FACTURAR": _skip_cliente_facturar,
    "IESS_APORTE": _skip_iess_aporte,
}


async def _should_skip(session: AsyncSession, *, event: NotificationEvent) -> str | None:
    """Motivo por el que el aviso ya no corresponde, o ``None`` si sigue vigente.

    Se vuelve a comprobar al entregar y no solo al programar: entre ambos
    momentos pueden pasar dias, y avisar de algo ya hecho es justo lo que hace
    que la gente ignore el resto de los avisos.

    Los avisos puramente informativos (``RESUMEN_MENSUAL``,
    ``IVA_PREVIEW_MENSUAL``) no tienen condicion de cierre: describen un mes,
    no piden una accion pendiente.
    """
    check = _SKIP_CHECKS.get(event.rule_type)
    if check is None:
        return None
    result: str | None = await check(session, event=event)
    return result


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
            rule_type=event.rule_type,
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

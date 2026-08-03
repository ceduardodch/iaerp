"""Plantilla del correo de cobranza, compartida por el envío manual y el programado.

Vive en ``services/`` y no en ``workers/collections.py`` porque la usan dos
caminos distintos: el recordatorio automático del scheduler y el botón "Enviar
correo" de la cartera (``services/receivables.py::send_real_reminder``). Tener
una sola plantilla evita que el cliente reciba dos mensajes con formato y datos
de pago distintos según quién lo disparó.

La plantilla y los datos bancarios son POR TENANT (``CollectionPolicy``): este
módulo solo rellena marcadores, nunca inventa una cuenta bancaria ni un monto.
"""

from __future__ import annotations

import html
from datetime import date
from decimal import Decimal

from app.models.receivables import CollectionPolicy

# Marcadores que el usuario puede escribir en asunto y cuerpo desde Configuración.
PLACEHOLDERS = (
    "{{empresa}}",
    "{{cliente}}",
    "{{saldo}}",
    "{{vencimiento}}",
    "{{dias_atraso}}",
    "{{cuenta_bancaria}}",
)


def format_usd(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def render_collection_email(
    *,
    policy: CollectionPolicy,
    company_name: str,
    party_name: str,
    open_amount: Decimal,
    due_date: date,
    as_of: date,
    body_override: str | None = None,
) -> tuple[str, str, str]:
    """Renderiza la plantilla del tenant y una tabla fiscalmente neutra.

    Devuelve ``(asunto, texto plano, html)``. ``body_override`` reemplaza el
    cuerpo configurado cuando el usuario escribe un mensaje propio al enviar a
    mano; el asunto, la tabla de saldo y los datos de pago se conservan para
    que un mensaje personalizado nunca pierda la información de cobro.
    """
    days_overdue = max(0, (as_of - due_date).days)
    values = {
        "{{empresa}}": company_name,
        "{{cliente}}": party_name,
        "{{saldo}}": format_usd(open_amount),
        "{{vencimiento}}": due_date.strftime("%d/%m/%Y"),
        "{{dias_atraso}}": str(days_overdue),
        "{{cuenta_bancaria}}": policy.payment_instructions or "Consulte con nuestro equipo.",
    }

    def render(text: str) -> str:
        for token, value in values.items():
            text = text.replace(token, value)
        return text

    subject = render(policy.email_subject)
    body = render(body_override if body_override is not None else policy.email_body)
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


__all__ = ["PLACEHOLDERS", "format_usd", "render_collection_email"]

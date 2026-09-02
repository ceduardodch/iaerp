"""Webhook de Brevo: entrega, rebote y queja.

Brevo **no firma** sus webhooks, asi que el secreto viaja en la ruta, igual que
el webhook de Evolution (``api/crm.py``). Sin ``BREVO_WEBHOOK_TOKEN`` el
endpoint responde 404: es preferible no existir a aceptar cualquier POST que
altere la bitacora de entregas.

El cruce con el envio es por ``provider_message_id``. Un evento cuyo id no
coincide con ningun envio nuestro se ignora en silencio y se cuenta como no
aplicado: es lo que se espera de un endpoint publico al que le pueden llegar
reintentos viejos o ruido.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.notifications import NotificationDelivery

# Eventos transaccionales de Brevo -> estado de NotificationDelivery.
# Solo se mapea lo que cambia el estado de una entrega. Los eventos de
# seguimiento (opened, clicked) se ignoran a proposito: saber si alguien abrio
# un aviso interno no justifica guardar ese rastro.
_EVENT_STATUS = {
    "delivered": "SENT",
    "hard_bounce": "BOUNCED",
    "soft_bounce": "BOUNCED",
    "blocked": "BOUNCED",
    "invalid_email": "BOUNCED",
    "error": "FAILED",
    "deferred": None,
    "spam": "COMPLAINED",
    "complaint": "COMPLAINED",
    "unsubscribed": "COMPLAINED",
}


def token_matches(candidate: str) -> bool:
    """Compara el token de la ruta en tiempo constante."""
    settings = get_settings()
    if settings.BREVO_WEBHOOK_TOKEN is None:
        return False
    return hmac.compare_digest(candidate, settings.BREVO_WEBHOOK_TOKEN.get_secret_value())


def _message_id(event: dict[str, Any]) -> str | None:
    """Id del mensaje, tolerando como lo escriba el proveedor.

    Brevo ha usado ``message-id`` y ``messageId`` segun el evento y la version;
    se aceptan ambos en vez de casarse con una sola forma y perder rebotes en
    silencio.
    """
    for key in ("message-id", "messageId", "message_id"):
        value = event.get(key)
        if value:
            return str(value)
    return None


async def apply_event(session: AsyncSession, *, event: dict[str, Any]) -> bool:
    """Aplica un evento a su entrega. ``True`` solo si cambio algo."""
    raw_event = str(event.get("event") or "").strip().lower()
    if raw_event not in _EVENT_STATUS:
        return False
    status = _EVENT_STATUS[raw_event]
    if status is None:
        # `deferred` es un reintento del proveedor, no un desenlace.
        return False

    message_id = _message_id(event)
    if message_id is None:
        return False

    delivery = await session.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.provider_message_id == message_id
        )
    )
    if delivery is None:
        return False

    # Un rebote posterior a la entrega si cuenta; un `delivered` que llega
    # despues de un rebote, no: el desenlace negativo es el que importa.
    if delivery.status in {"BOUNCED", "COMPLAINED"} and status == "SENT":
        return False

    delivery.status = status
    if status == "SENT" and delivery.sent_at is None:
        delivery.sent_at = datetime.now(UTC)
    if status in {"BOUNCED", "COMPLAINED", "FAILED"}:
        reason = str(event.get("reason") or raw_event)
        delivery.error_message = reason[:1000]
    return True


async def process_payload(session: AsyncSession, *, payload: Any) -> int:
    """Aplica el lote del webhook. Devuelve cuantas entregas cambiaron.

    Brevo puede mandar un evento suelto o una lista; se aceptan ambos.
    """
    events = payload if isinstance(payload, list) else [payload]
    applied = 0
    for event in events:
        if isinstance(event, dict):
            applied += await apply_event(session, event=event)
    return applied


__all__ = ["apply_event", "process_payload", "token_matches"]

"""Protocolo ``Notifier`` para envío de recordatorios de cobranza (Sprint 3, decisión 8).

``docs/sprints/sprint-03.md`` (decision 8) define dos implementaciones:
``StubNotifier`` (activa por defecto, sin apertura de red, ver ``stub.py``) y
un ``EmailNotifier`` placeholder para un sprint futuro con proveedor real de
correo (no implementado aquí). Ambas deben respetar este mismo ``Protocol`` para
que ``services/receivables.py`` no dependa de qué implementación está activa.

Los estados devueltos (``ReminderStatus``) son los mismos nombres de estado que
persiste ``CollectionReminder`` (ver ``models/receivables.py``), para que el
servicio los use sin traducir un vocabulario intermedio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

# Estados posibles de un recordatorio (coincidentes con CollectionReminder.status)
ReminderStatus = Literal["STUBBED", "SENT", "FAILED"]


@dataclass(frozen=True)
class ReminderRequest:
    """Solicitud de envío de recordatorio.

    ``channel`` puede ser "email", "sms", "whatsapp", etc.
    ``template_id`` identifica la plantilla a usar (ej: "overdue_3_days", "payment_reminder")
    ``recipient`` es el destino (ej: email para canal email, teléfono para sms)
    ``party_id`` identifica el cliente para verificar consent_opt_out
    """

    channel: str
    template_id: str
    recipient: str
    party_id: str


@dataclass(frozen=True)
class ReminderResult:
    """Respuesta de ``send``.

    ``reminder_id`` es el UUID del ``CollectionReminder`` creado (o None si se rechazó)
    ``status`` indica el estado final (STUBBED, SENT, FAILED)
    ``error_message`` puede contener detalles si status==FAILED
    """

    reminder_id: str | None
    status: ReminderStatus
    error_message: str | None = None


class Notifier(Protocol):
    """Proveedor de envío de recordatorios (real o stub).

    Ninguna implementación decide políticas de cuándo recordar: eso es
    responsabilidad exclusiva de ``services/receivables.py``. Este protocolo
    solo se encarga de enviar (o stubear) el recordatorio y crear el
    ``CollectionReminder`` correspondiente.

    Toda implementación debe:
    - Verificar ``party.consent_opt_out`` y rechazar si es True
    - Crear un ``CollectionReminder`` con el estado correspondiente
    - Retornar un ``ReminderResult`` con el reminder_id creado
    """

    async def send(self, reminder: ReminderRequest) -> ReminderResult: ...


__all__ = [
    "Notifier",
    "ReminderRequest",
    "ReminderResult",
    "ReminderStatus",
]

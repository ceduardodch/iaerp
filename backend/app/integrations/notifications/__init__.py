"""Integraciones de notificaciones: dos contratos distintos, a propósito.

**Cobranza al cliente** (Sprint 3):
- ``protocol.py``: contrato ``Notifier``, ``ReminderRequest``, ``ReminderResult``
- ``stub.py``: implementación stub sin apertura de red (activa por defecto)

**Avisos internos al equipo** (F1 del plan de avisos):
- ``email_sender.py``: contrato ``EmailSender`` y ``StubEmailSender``

No comparten protocolo porque no hacen lo mismo: ``Notifier`` además persiste
el ``CollectionReminder``, mientras que ``EmailSender`` solo transporta y deja
la persistencia en ``services/notifications/``. El envío real por Brevo llega
en F2 sobre el segundo contrato.
"""

from app.integrations.notifications.email_sender import (
    EmailMessage,
    EmailSender,
    EmailSendResult,
    EmailSendStatus,
    StubEmailSender,
)
from app.integrations.notifications.protocol import (
    Notifier,
    ReminderRequest,
    ReminderResult,
    ReminderStatus,
)
from app.integrations.notifications.stub import StubNotifier

__all__ = [
    "EmailMessage",
    "EmailSendResult",
    "EmailSendStatus",
    "EmailSender",
    "Notifier",
    "ReminderRequest",
    "ReminderResult",
    "ReminderStatus",
    "StubEmailSender",
    "StubNotifier",
]

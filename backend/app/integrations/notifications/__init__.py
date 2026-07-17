"""Integraciones de notificaciones (recordatorios de cobranza).

Este paquete contiene el protocolo ``Notifier`` y sus implementaciones:
- ``protocol.py``: define el contrato Notifier, ReminderRequest y ReminderResult
- ``stub.py``: implementación stub sin apertura de red (activa por defecto)

Un sprint futuro agregará ``email.py`` con una implementación real usando
un proveedor de correo (Sendgrid, AWS SES, etc).
"""

from app.integrations.notifications.protocol import (
    Notifier,
    ReminderRequest,
    ReminderResult,
    ReminderStatus,
)
from app.integrations.notifications.stub import StubNotifier

__all__ = [
    "Notifier",
    "ReminderRequest",
    "ReminderResult",
    "ReminderStatus",
    "StubNotifier",
]

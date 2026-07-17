"""Implementación stub de ``Notifier`` sin apertura de red (Sprint 3, decisión 8).

``StubNotifier`` crea un ``CollectionReminder`` con status="STUBBED" sin enviar
ninguna comunicación real. Es la implementación activa por defecto en
development/test para permitir probar el flujo de cobranza sin depender de un
proveedor de correo/SMS real.

Respeta ``party.consent_opt_out``: si el cliente ha optado out de notificaciones,
rechaza el recordatorio y retorna un ReminderResult con reminder_id=None.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.notifications.protocol import (
    ReminderRequest,
    ReminderResult,
)
from app.models.masters import Party
from app.models.receivables import CollectionReminder


class StubNotifier:
    """Notifier stub que solo crea el registro en BD sin enviar nada.

    Útil para development y tests: permite validar el flujo completo de
    cobranza (selección de clientes, creación de recordatorios, persistencia)
    sin depender de credenciales externas ni conexión a servicios de messaging.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def send(self, reminder: ReminderRequest) -> ReminderResult:
        """Crea un CollectionReminder con status=STUBBED sin enviar nada.

        Verifica primero que ``party.consent_opt_out`` sea False (o None).
        Si el cliente ha optado out, retorna con reminder_id=None y no crea
        ningún registro.

        ``reminder.party_id`` es el UUID del party como string.
        """
        party_uuid = uuid.UUID(reminder.party_id)

        # Buscar el party para verificar consent_opt_out
        party_result = await self.session.execute(
            select(Party).where(Party.id == party_uuid)
        )
        party = party_result.scalar_one_or_none()

        if party is None:
            return ReminderResult(
                reminder_id=None,
                status="FAILED",
                error_message=f"Party {reminder.party_id} not found",
            )

        # Verificar consent_opt_out: si es True, rechazar el recordatorio
        if getattr(party, "consent_opt_out", False):
            return ReminderResult(
                reminder_id=None,
                status="FAILED",
                error_message=f"Party {reminder.party_id} has opted out of notifications",
            )

        # Crear el CollectionReminder con status=STUBBED
        collection_reminder = CollectionReminder(
            tenant_id=party.tenant_id,
            party_id=party_uuid,
            channel=reminder.channel,
            template_id=reminder.template_id,
            recipient=reminder.recipient,
            status="STUBBED",
        )

        self.session.add(collection_reminder)
        await self.session.flush()

        return ReminderResult(
            reminder_id=str(collection_reminder.id),
            status="STUBBED",
            error_message=None,
        )


__all__ = ["StubNotifier"]

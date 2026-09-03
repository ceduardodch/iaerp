"""Esquemas del canal de avisos internos (F2).

Ninguno de estos modelos transporta credenciales: con una sola cuenta Brevo de
plataforma, la clave vive en la configuracion del servidor y nunca entra ni
sale por HTTP. Lo que viaja aqui es identidad de remitente y diagnostico.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, model_validator

from app.schemas.base import APIModel


class ChannelAccountUpdate(APIModel):
    """Con que cara salen los avisos de esta empresa."""

    sender_name: str | None = Field(default=None, max_length=200)
    # Solo sirve si el dominio esta autenticado en la cuenta Brevo de IAERP;
    # si no lo esta, el envio se rechaza. Por eso el default es el remitente
    # de plataforma y esto es opcional.
    sender_email: EmailStr | None = None
    reply_to: EmailStr | None = None


class ChannelAccountRead(APIModel):
    """Estado del canal, pensado para que un fallo se vea antes de enviar."""

    provider: str
    platform_key_configured: bool
    sender_email: str | None
    sender_name: str
    reply_to: str | None
    ready: bool
    blocking_reason: str | None


class ChannelTestRequest(APIModel):
    recipient: EmailStr


class ChannelTestResult(APIModel):
    provider: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None


# --------------------------------------------------------------------------
# Reglas, plantillas, bitácora y calendario de facturación (F4).
#
# Estos esquemas son la superficie de configuración del módulo: encender o
# apagar una regla, editar una plantilla, revisar/reenviar/dar acuse de un
# aviso ya programado, y mantener el calendario de facturación por cliente
# (``PartyBillingSchedule``). Ninguno transporta credenciales; eso sigue
# siendo exclusivo de ``ChannelAccountUpdate``.
# --------------------------------------------------------------------------


class NotificationRuleRead(APIModel):
    id: uuid.UUID
    rule_type: str
    name: str
    enabled: bool
    schedule_kind: str
    days_of_month: str | None
    offsets_days: str | None
    send_hour: int
    channels: str
    audience_kind: str
    audience_roles: list[str]
    audience_emails: list[str]
    require_ack: bool
    updated_at: datetime


class NotificationRuleUpdate(APIModel):
    """Reemplazo completo de la parametrización de una regla (PUT, no parche).

    ``rule_type`` y ``name`` no son editables: vienen del catálogo y no se
    exponen aquí, así que no hay riesgo de que un PUT los pise.
    """

    enabled: bool
    schedule_kind: Literal["DAY_OF_MONTH", "OFFSET_TO_DUE", "LAST_BUSINESS_DAY", "WEEKDAY"]
    days_of_month: str | None = Field(default=None, max_length=100)
    offsets_days: str | None = Field(default=None, max_length=100)
    send_hour: int = Field(ge=0, le=23)
    channels: str = Field(default="EMAIL", max_length=100)
    audience_kind: Literal["TENANT_USERS", "EXPLICIT_EMAILS", "PARTY"] = "TENANT_USERS"
    audience_roles: list[str] = Field(default_factory=list)
    audience_emails: list[EmailStr] = Field(default_factory=list)
    require_ack: bool = False


class NotificationTemplateRead(APIModel):
    rule_type: str
    subject: str
    body: str
    is_custom: bool  # True = fila propia del tenant, False = usando el default del catálogo


class NotificationTemplateUpdate(APIModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5000)


class NotificationTemplatePreviewRequest(APIModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5000)


class NotificationTemplatePreviewResult(APIModel):
    subject: str
    body_text: str
    body_html: str


class NotificationDeliveryRead(APIModel):
    id: uuid.UUID
    recipient: str
    channel: str
    provider: str
    status: str
    error_message: str | None
    sent_at: datetime | None


class NotificationEventRead(APIModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    rule_type: str
    status: str
    scheduled_at: datetime
    attempts: int
    error_message: str | None
    sent_at: datetime | None
    ack_at: datetime | None
    ack_by: str | None
    # De ``payload["period_label"]`` cuando el aviso lo trae; ``None`` si no
    # aplica. Se lee del snapshot y no se recalcula, igual que el resto del
    # correo: el evento dice lo que se calculó al programarlo.
    period_label: str | None


class NotificationEventDetailRead(NotificationEventRead):
    payload: dict[str, object]
    deliveries: list[NotificationDeliveryRead]


class NotificationBillingScheduleRead(APIModel):
    id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    contract_id: uuid.UUID | None
    day_of_month: int
    frequency: str
    anchor_month: int | None
    amount_hint: Decimal | None
    notes: str | None
    active: bool


class NotificationBillingScheduleCreate(APIModel):
    party_id: uuid.UUID
    contract_id: uuid.UUID | None = None
    day_of_month: int = Field(ge=1, le=31)
    frequency: Literal["MONTHLY", "BIMONTHLY", "QUARTERLY", "ANNUAL"] = "MONTHLY"
    anchor_month: int | None = Field(default=None, ge=1, le=12)
    amount_hint: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_anchor_month(self) -> NotificationBillingScheduleCreate:
        """Refleja en 422 el ``CHECK anchor_month_required`` de la base.

        Sin ancla, un ciclo trimestral/bimestral/anual no sabe desde qué mes
        se cuenta y el aviso caería en el mes equivocado; la base ya lo
        impide con un CHECK, pero dejar que ese CHECK sea el único guardián
        convierte el error en un 500 en vez de un 422 legible.
        """
        if self.frequency != "MONTHLY" and self.anchor_month is None:
            raise ValueError(
                "Un ciclo no mensual necesita anchor_month para saber desde qué mes se cuenta"
            )
        return self


class NotificationBillingScheduleUpdate(NotificationBillingScheduleCreate):
    active: bool = True


__all__ = [
    "ChannelAccountRead",
    "ChannelAccountUpdate",
    "ChannelTestRequest",
    "ChannelTestResult",
    "NotificationBillingScheduleCreate",
    "NotificationBillingScheduleRead",
    "NotificationBillingScheduleUpdate",
    "NotificationDeliveryRead",
    "NotificationEventDetailRead",
    "NotificationEventRead",
    "NotificationRuleRead",
    "NotificationRuleUpdate",
    "NotificationTemplatePreviewRequest",
    "NotificationTemplatePreviewResult",
    "NotificationTemplateRead",
    "NotificationTemplateUpdate",
]

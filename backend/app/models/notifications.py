"""Modelos del modulo de avisos internos (F1 de ``docs/NOTIFICATIONS_MODULE_PLAN.md``).

Estos avisos le hablan al **equipo interno** ("toca declarar", "toca facturar a
este cliente"), no al cliente. La cobranza al cliente ya existe aparte en
``CollectionReminder`` (``models/receivables.py``) y sigue su propio camino por
Gmail; no se mezclan porque tienen destinatarios, plantillas y reglas de
opt-out distintas.

El diseno separa tres cosas que en cobranza estaban juntas:

- ``NotificationRule``: **cuando** avisar. Es la parametrizacion; cambiar el dia
  de un aviso no debe requerir tocar codigo.
- ``NotificationTemplate``: **que dice**, con marcadores por tenant.
- ``NotificationChannelAccount``: **por donde sale** (Brevo, stub).

``NotificationEvent`` es una ocurrencia ya programada y ``NotificationDelivery``
un envio concreto a un destinatario. Se separan porque un mismo aviso puede ir a
varias personas y cada una rebota o se da de baja por su cuenta.

Se declara el esquema completo en una sola migracion aunque F1 solo ejercite un
tipo de aviso, por el mismo motivo que ``Movement``/``CustomerCredit`` en el
Sprint 3: agregar columnas despues, con filas ya escritas, cuesta mas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin

# Catalogo cerrado de avisos. Se declara completo desde F1 -- aunque solo
# IVA_DECLARACION este implementado -- para que sumar un aviso del catalogo no
# obligue a una migracion nueva solo por ampliar el CHECK.
RULE_TYPES = (
    "CLIENTE_FACTURAR",
    "IVA_DECLARACION",
    "IVA_PREVIEW_MENSUAL",
    "RESUMEN_MENSUAL",
    "IESS_APORTE",
    "NOMINA_ROL",
    "CARTERA_VENCIDA",
    "CXP_PROXIMO_PAGO",
    "RENOVACION_CONTRATO",
    "SRI_RECHAZO",
    "EVIDENCIA_INCOMPLETA",
)

# Como se calculan las fechas de un aviso:
# - DAY_OF_MONTH: dias fijos del mes (``days_of_month`` = "1,10").
# - OFFSET_TO_DUE: dias relativos a una fecha limite (``offsets_days`` = "-7,-1,0").
# - LAST_BUSINESS_DAY: ultimo dia habil del mes.
# - WEEKDAY: dia de la semana (0=lunes), en ``days_of_month``.
SCHEDULE_KINDS = ("DAY_OF_MONTH", "OFFSET_TO_DUE", "LAST_BUSINESS_DAY", "WEEKDAY")

# A quien se le avisa. PARTY existe para avisos que si miran a un tercero
# (por ejemplo una futura confirmacion al cliente), pero F1 solo usa los dos
# primeros: este modulo es de avisos internos.
AUDIENCE_KINDS = ("TENANT_USERS", "EXPLICIT_EMAILS", "PARTY")

# STUBBED existe para que la bitacora de un ambiente sin proveedor real no sea
# indistinguible de la de produccion: un evento procesado del que no salio
# ningun correo no puede figurar como SENT.
EVENT_STATUSES = (
    "PENDING",
    "PROCESSING",
    "SENT",
    "STUBBED",
    "SKIPPED",
    "FAILED",
    "CANCELLED",
)
DELIVERY_STATUSES = ("PENDING", "STUBBED", "SENT", "FAILED", "BOUNCED", "COMPLAINED")

_RULE_TYPES_SQL = ", ".join(f"'{value}'" for value in RULE_TYPES)
_SCHEDULE_KINDS_SQL = ", ".join(f"'{value}'" for value in SCHEDULE_KINDS)
_AUDIENCE_KINDS_SQL = ", ".join(f"'{value}'" for value in AUDIENCE_KINDS)
_EVENT_STATUSES_SQL = ", ".join(f"'{value}'" for value in EVENT_STATUSES)
_DELIVERY_STATUSES_SQL = ", ".join(f"'{value}'" for value in DELIVERY_STATUSES)


class NotificationChannelAccount(TimestampMixin, Base):
    """Identidad de remitente por tenant (1:1, como ``CollectionPolicy``).

    Brevo es **una sola cuenta de plataforma** (decidido el 2026-09-02), asi
    que aqui NO hay ninguna credencial: la clave vive en ``BREVO_API_KEY``, en
    la configuracion del servidor. Lo que guarda esta tabla es con que cara
    sale el correo de cada empresa.

    El ``From`` usa siempre el dominio verificado de IAERP -- es el unico
    autenticado en la cuenta (SPF/DKIM) -- y ``reply_to`` devuelve la
    conversacion a la empresa. ``sender_email`` queda para el caso en que un
    tenant autentique su propio dominio en esa misma cuenta.

    ``api_key_vault_ref`` sobrevive de un diseno anterior con una cuenta por
    tenant; hoy no se usa.
    """

    __tablename__ = "notification_channel_accounts"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('STUB', 'BREVO')",
            name="provider_valid",
        ),
        CheckConstraint(
            "status IN ('NOT_CONFIGURED', 'PENDING_VERIFICATION', 'ACTIVE', 'ERROR')",
            name="status_valid",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(20), default="STUB")
    api_key_vault_ref: Mapped[str | None] = mapped_column(String(200))
    sender_email: Mapped[str | None] = mapped_column(String(320))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    reply_to: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(30), default="NOT_CONFIGURED")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))


class NotificationRule(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cuando avisar. Varias reglas pueden compartir ``rule_type``.

    Eso es a proposito: "mas de un correo que se lance" para la misma
    obligacion, con distinto publico o distinta antelacion, tiene que ser
    configuracion y no una rama de codigo.

    Nace ``enabled=False``. Un modulo que empieza mandando correos solo, sin que
    nadie lo pida, se gana un filtro de spam el primer dia.
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notification_rules_tenant_id"),
        CheckConstraint(f"rule_type IN ({_RULE_TYPES_SQL})", name="rule_type_valid"),
        CheckConstraint(
            f"schedule_kind IN ({_SCHEDULE_KINDS_SQL})",
            name="schedule_kind_valid",
        ),
        CheckConstraint(
            f"audience_kind IN ({_AUDIENCE_KINDS_SQL})",
            name="audience_kind_valid",
        ),
        CheckConstraint("send_hour BETWEEN 0 AND 23", name="send_hour_valid"),
        Index("ix_notification_rules_tenant_enabled", "tenant_id", "enabled"),
    )

    rule_type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_kind: Mapped[str] = mapped_column(String(30))
    # Listas separadas por coma, mismo formato que ``CollectionPolicy.offsets_days``.
    days_of_month: Mapped[str | None] = mapped_column(String(100))
    offsets_days: Mapped[str | None] = mapped_column(String(100))
    send_hour: Mapped[int] = mapped_column(Integer, default=8)
    channels: Mapped[str] = mapped_column(String(100), default="EMAIL")
    audience_kind: Mapped[str] = mapped_column(String(30), default="TENANT_USERS")
    audience_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    audience_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Ajustes propios de cada tipo de aviso (umbrales, filtros).
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Exige que una persona confirme "hecho"; para IESS y declaracion.
    require_ack: Mapped[bool] = mapped_column(Boolean, default=False)


class NotificationTemplate(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Asunto y cuerpo por cuenta. Sin fila aqui se usa el default del codigo."""

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_notification_templates_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "rule_type",
            name="uq_notification_templates_tenant_rule_type",
        ),
        CheckConstraint(f"rule_type IN ({_RULE_TYPES_SQL})", name="rule_type_valid"),
    )

    rule_type: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)


class NotificationEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Una ocurrencia programada de un aviso.

    ``dedupe_key`` es la pieza critica del modulo: unica por tenant, evita que
    el planificador -- que corre cada minuto -- programe dos veces el mismo
    aviso, incluso despues de un reinicio. Cumple el mismo papel que
    ``correlation_id`` en los recordatorios de cobranza.

    ``payload`` guarda el **snapshot** de las cifras al momento de programar,
    para que el correo diga lo mismo que se calculo y no lo que el mundo hizo
    despues.
    """

    __tablename__ = "notification_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "rule_id"],
            ["notification_rules.tenant_id", "notification_rules.id"],
            name="fk_notification_events_tenant_rule",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_notification_events_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_notification_events_tenant_dedupe_key",
        ),
        CheckConstraint(f"rule_type IN ({_RULE_TYPES_SQL})", name="rule_type_valid"),
        CheckConstraint(f"status IN ({_EVENT_STATUSES_SQL})", name="status_valid"),
        Index("ix_notification_events_due", "tenant_id", "status", "scheduled_at"),
    )

    rule_id: Mapped[uuid.UUID | None]
    rule_type: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_by: Mapped[str | None] = mapped_column(String(200))


class NotificationDelivery(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Un envio a un destinatario concreto de un ``NotificationEvent``.

    Uno por persona, no uno por evento: asi se puede rastrear un rebote o una
    baja individual sin perder de vista que el aviso si salio para el resto.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["notification_events.tenant_id", "notification_events.id"],
            name="fk_notification_deliveries_tenant_event",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_notification_deliveries_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "recipient",
            name="uq_notification_deliveries_event_recipient",
        ),
        CheckConstraint(f"status IN ({_DELIVERY_STATUSES_SQL})", name="status_valid"),
        Index("ix_notification_deliveries_tenant_event", "tenant_id", "event_id"),
    )

    event_id: Mapped[uuid.UUID]
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL")
    recipient: Mapped[str] = mapped_column(String(320))
    provider: Mapped[str] = mapped_column(String(20), default="STUB")
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    error_message: Mapped[str | None] = mapped_column(String(1000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "AUDIENCE_KINDS",
    "DELIVERY_STATUSES",
    "EVENT_STATUSES",
    "RULE_TYPES",
    "SCHEDULE_KINDS",
    "NotificationChannelAccount",
    "NotificationDelivery",
    "NotificationEvent",
    "NotificationRule",
    "NotificationTemplate",
]

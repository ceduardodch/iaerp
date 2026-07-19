"""Schemas del contexto Receivables (Sprint 3).

``AccountItem`` ya esta declarado en ``contracts/openapi.yaml`` desde
Sprint 0; este modulo lo implementa tal cual (mismos campos, mismo
``enum`` de ``status``). Fase 2 agrego los schemas de escritura
(``PaymentInput``/``RetentionInput``/``DiscountInput``) y de lectura de
movimientos (``MovementRead``), todos tal como los declara
``contracts/openapi.yaml`` sin renombrar ni cambiar forma. Fase 3 agrega
``aging`` (opcional, aditivo) a ``AccountItemRead``, el schema de resumen
``AgingSummaryRead`` (E5-05) y el input del reverso ``ReversalInput``
(E5-09).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import APIModel

AccountItemStatus = Literal["OPEN", "PARTIAL", "OVERDUE", "SETTLED", "VOIDED"]
PaymentMethod = Literal["TRANSFER", "CHECK", "CASH", "CARD", "OTHER"]
RetentionKind = Literal["RETENTION_IVA", "RETENTION_RENTA", "OTHER"]
MovementType = Literal["PAYMENT", "RETENTION", "DISCOUNT", "CREDIT_NOTE", "REVERSAL"]
AgingBucket = Literal["CURRENT", "1-15", "16-30", "31-60", "61-90", "90+"]


class AgingRead(APIModel):
    """Bucket de aging del receivable completo (el peor entre sus cuotas abiertas).

    Campo de solo lectura, opcional (aditivo, decision 10 del sprint): un
    receivable sin cuotas abiertas en mora es ``CURRENT``/``daysOverdue=0``.
    """

    bucket: AgingBucket
    days_overdue: int = Field(ge=0)


class AccountItemRead(APIModel):
    id: uuid.UUID
    party_id: uuid.UUID
    status: AccountItemStatus
    original_amount: Decimal
    open_amount: Decimal
    currency: Literal["USD"] = "USD"
    due_date: date | None = None
    aging: AgingRead | None = None


class RetentionInput(APIModel):
    """Retencion aplicada dentro de un cobro (``PaymentInput.retentions``).

    Reduce el saldo igual que un cobro, pero se registra como ``Movement``
    tipo ``RETENTION`` con su propio ``support_reference`` (comprobante de
    retencion) para trazabilidad.
    """

    kind: RetentionKind
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reason: str = Field(min_length=3)
    document_reference: str | None = None


class DiscountInput(APIModel):
    """Descuento aplicado dentro de un cobro (``PaymentInput.discounts``).

    Reduce el saldo igual que un cobro, registrado como ``Movement`` tipo
    ``DISCOUNT`` con el motivo como ``support_reference``.
    """

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reason: str = Field(min_length=3)


class PaymentInput(APIModel):
    """Cobro parcial o total, con retenciones/descuentos anidados (E5-03/E5-04).

    La suma de ``cash_amount`` + retenciones + descuentos debe ser mayor que
    cero y nunca superar el saldo abierto del receivable (422 si excede, ver
    ``services/receivables.py::record_payment``).
    """

    cash_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    payment_date: date
    method: PaymentMethod | None = None
    reference: str | None = None
    retentions: list[RetentionInput] = Field(default_factory=list)
    discounts: list[DiscountInput] = Field(default_factory=list)


class MovementRead(APIModel):
    """Fila de ``Movement`` para el historial de aplicaciones de un receivable."""

    id: uuid.UUID
    receivable_id: uuid.UUID
    installment_id: uuid.UUID
    movement_type: MovementType
    amount: Decimal
    support_reference: str | None
    reversed_movement_id: uuid.UUID | None
    actor_id: str
    created_at: datetime


class ReversalInput(APIModel):
    """Cuerpo de ``POST /receivables/{id}/movements/{movementId}/reversal`` (E5-09).

    ``reason`` es obligatorio (decision 7 del sprint: la auditoria del
    reverso incluye el motivo); se guarda como ``support_reference`` del
    ``Movement`` ``REVERSAL`` creado.
    """

    reason: str = Field(min_length=3)


class AgingBucketTotalRead(APIModel):
    """Total agregado de un bucket dentro de ``AgingSummaryRead``."""

    bucket: AgingBucket
    total: Decimal
    installment_count: int = Field(ge=0)


class PartyAgingBucketTotalRead(APIModel):
    """Total agregado de un bucket para un cliente especifico."""

    party_id: uuid.UUID
    bucket: AgingBucket
    total: Decimal
    installment_count: int = Field(ge=0)


class AgingSummaryRead(APIModel):
    """Resumen de aging por tenant (``GET /receivables/aging``, E5-05).

    ``as_of`` es la fecha de corte local (``America/Guayaquil``) usada para
    clasificar cada cuota; por defecto hoy, overrideable por query param
    para reproducibilidad en pruebas.
    """

    as_of: date
    buckets: list[AgingBucketTotalRead]
    by_party: list[PartyAgingBucketTotalRead]


class ReminderInput(APIModel):
    """Input para envío manual de recordatorio (Sprint 3, decisión 8).

    ``channel`` puede ser "email", "sms", "whatsapp", etc.
    ``template_id`` identifica la plantilla a usar (ej: "overdue_3_days")
    ``message`` es un mensaje opcional personalizado
    Todos los campos son opcionales: el servicio puede usar defaults
    """

    channel: str | None = None
    template_id: str | None = None
    message: str | None = None
    scheduled_at: datetime | None = None


class ReminderRead(APIModel):
    id: uuid.UUID
    party_id: uuid.UUID
    receivable_id: uuid.UUID | None
    installment_id: uuid.UUID | None
    channel: str
    template_id: str
    recipient: str
    status: str
    scheduled_at: datetime | None
    sent_at: datetime | None
    attempts: int
    error_message: str | None


def _default_collection_channels() -> list[Literal["EMAIL", "WHATSAPP"]]:
    return ["EMAIL"]


class CollectionPolicyUpdate(APIModel):
    enabled: bool = False
    offsets_days: list[int] = Field(default_factory=lambda: [-3, 0, 3, 7, 15])
    channels: list[Literal["EMAIL", "WHATSAPP"]] = Field(
        default_factory=_default_collection_channels
    )
    send_hour: int = Field(default=9, ge=0, le=23)
    email_template_id: str = Field(default="payment_reminder", max_length=100)
    whatsapp_template_id: str = Field(default="payment_reminder", max_length=100)


class CollectionPolicyRead(CollectionPolicyUpdate):
    updated_at: datetime


__all__ = [
    "AccountItemRead",
    "AccountItemStatus",
    "AgingBucket",
    "AgingBucketTotalRead",
    "AgingRead",
    "AgingSummaryRead",
    "DiscountInput",
    "MovementRead",
    "MovementType",
    "PartyAgingBucketTotalRead",
    "PaymentInput",
    "PaymentMethod",
    "ReminderInput",
    "ReminderRead",
    "CollectionPolicyRead",
    "CollectionPolicyUpdate",
    "ReversalInput",
    "RetentionInput",
    "RetentionKind",
]

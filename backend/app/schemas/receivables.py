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

from app.core.collection_defaults import DEFAULT_COLLECTION_EMAIL_BODY
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
    invoice_sequential: str | None = None
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
    document_reference: str = Field(min_length=3, max_length=120)


class RetentionXmlPreviewItem(APIModel):
    """Retención leída de un comprobante SRI autorizado, sin registrar cobro."""

    kind: RetentionKind
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    base_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    rate: Decimal = Field(ge=0, max_digits=9, decimal_places=6)
    sri_retention_code: str = Field(min_length=1, max_length=20)


class RetentionXmlPreviewRead(APIModel):
    """Resultado verificable de leer un XML de retención autorizado.

    El endpoint no persiste el archivo ni crea movimientos: la persona revisa
    el resultado y confirma el cobro en el flujo normal.
    """

    authorization_number: str = Field(min_length=1, max_length=49)
    supporting_document: str = Field(min_length=1, max_length=20)
    issue_date: date
    retentions: list[RetentionXmlPreviewItem] = Field(min_length=1)


class RetentionBatchItemRead(APIModel):
    file_name: str
    receivable_id: uuid.UUID | None = None
    authorization_number: str | None = None
    supporting_document: str | None = None
    invoice_sequential: str | None = None
    issue_date: date | None = None
    total: Decimal = Decimal("0.00")
    status: Literal["MATCHED", "REVIEW_REQUIRED"]
    detail: str


class RetentionBatchRead(APIModel):
    items: list[RetentionBatchItemRead]


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
    effective_date: date | None
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


class ReceivableDueDateUpdate(APIModel):
    """Corrección comercial del vencimiento de una cuenta histórica."""

    due_date: date
    reason: str = Field(min_length=3, max_length=500)


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


class CollectionsBreakdownRead(APIModel):
    """Cómo se cobró: cuánto entró en dinero y cuánto se fue en retenciones.

    Responde la pregunta operativa "de lo que cobré, ¿cuánto es efectivo y
    cuánto retención?". Solo cuenta movimientos activos: ni las filas
    ``REVERSAL`` ni los movimientos que un ``REVERSAL`` ya deshizo, con la
    misma regla que ``compute_installment_balance`` para que el desglose nunca
    contradiga el saldo mostrado en la cartera.

    ``cash_amount`` agrupa los ``PAYMENT`` (transferencia, cheque, efectivo,
    tarjeta): dinero que efectivamente entró. ``retention_amount`` son los
    ``RETENTION``: valor legalmente retenido por el cliente, que se recupera
    ante el SRI, no en caja. ``credit_amount`` junta ``CREDIT_NOTE`` y
    ``DISCOUNT``: reducen la deuda sin ser cobro.

    ``from_date``/``to_date`` filtran por ``Movement.effective_date`` (la
    fecha real del cobro), no por la fecha técnica de registro.
    """

    from_date: date | None
    to_date: date | None
    cash_amount: Decimal
    cash_count: int = Field(ge=0)
    retention_amount: Decimal
    retention_count: int = Field(ge=0)
    credit_amount: Decimal
    credit_count: int = Field(ge=0)
    # cash + retention: lo que realmente saldó factura por vía de cobro.
    settled_amount: Decimal
    # Porcentaje del cobro que se fue en retenciones (0 si no hubo cobro).
    retention_share: Decimal


class MonthlyCollectionRead(APIModel):
    """Un mes de la serie de cobro (``GET /receivables/collections/monthly``)."""

    year: int
    month: int
    cash_amount: Decimal
    retention_amount: Decimal
    settled_amount: Decimal


class CollectionsHistoryRead(APIModel):
    """Serie mensual de cobro, para leer la tendencia y no solo el total.

    Un total sin comparación no dice si vas mejor o peor. Esta serie alimenta
    la minigráfica y la variación contra el mes anterior en el tablero.

    Los meses SIN cobro aparecen en cero en vez de faltar: una serie con huecos
    dibuja una tendencia falsa, porque la línea saltaría de un mes a otro no
    contiguo como si fueran consecutivos.
    """

    months: list[MonthlyCollectionRead]


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
    # Evita que una segunda pulsación o una nueva clave duplique un envío ya
    # realizado. Para insistir, la persona debe dejar el motivo.
    resend_reason: str | None = Field(default=None, min_length=3, max_length=500)


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
    delivery_status: str
    delivered_at: datetime | None
    read_at: datetime | None


class CollectionContactCreate(APIModel):
    channel: Literal["CALL", "EMAIL", "WHATSAPP", "NOTE"]
    outcome: Literal["PENDING", "CONTACTED", "PROMISE_TO_PAY", "NO_RESPONSE", "WRONG_CONTACT"]
    note: str | None = Field(default=None, max_length=1000)
    occurred_at: datetime | None = None


class CollectionHistoryEntryRead(APIModel):
    id: uuid.UUID
    kind: Literal["REMINDER", "CONTACT"]
    occurred_at: datetime
    channel: str
    outcome: str
    note: str | None = None
    recipient: str | None = None
    delivery_status: str | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None


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
    email_subject: str = Field(
        default="Recordatorio de pago - {{empresa}}", min_length=3, max_length=200
    )
    email_body: str = Field(
        default=DEFAULT_COLLECTION_EMAIL_BODY,
        min_length=3,
        max_length=5000,
    )
    payment_instructions: str = Field(default="", max_length=1500)


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
    "CollectionContactCreate",
    "CollectionHistoryEntryRead",
    "ReversalInput",
    "ReceivableDueDateUpdate",
    "RetentionInput",
    "RetentionXmlPreviewItem",
    "RetentionXmlPreviewRead",
    "RetentionKind",
]

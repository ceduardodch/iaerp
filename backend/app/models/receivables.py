"""Modelos del contexto Receivables (Sprint 3, Fase 1: E5-01/E5-02).

``Receivable`` nace 1:1 de una factura ``AUTHORIZED`` (``sales_document_id``,
``UniqueConstraint`` que impide dos receivables para el mismo documento) y
sus ``ReceivableInstallment`` materializan el plan de pago declarado en
``InvoiceInput.installments`` en el momento de emision (ver
``workers/receivables.py::handle_invoice_authorized``). La suma de
``ReceivableInstallment.amount`` de un receivable siempre es igual a su
``original_amount`` -- verificado por el creador (ver
``services/receivables.py``/``workers/receivables.py``), nunca por un
``CHECK`` de base de datos porque involucra una agregacion entre filas.

``Movement`` y ``CustomerCredit`` se definen aqui (misma migracion) aunque su
logica de escritura llega en fases 2/3 del Sprint 3 (cobros, notas de
credito, reverso): declarar el esquema completo ahora evita una migracion
adicional para agregar columnas a una tabla que ya tendria filas. Ningun caso
de uso de esta fase escribe en ``Movement``/``CustomerCredit`` todavia.

Reglas de saldo (``docs/sprints/sprint-03.md`` decision 2): el saldo NUNCA se
guarda como columna de verdad; se calcula sumando movimientos activos bajo
``SELECT ... FOR UPDATE`` sobre la fila ``Receivable`` (no la cuota
individual), mismo patron que ``Sequence``/``Tenant`` en Sprint 2. Dinero
siempre ``Numeric(18, 2)``/``Decimal`` (ADR 0004, igual que
``SalesDocument``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin

# Estados de Receivable (docs/03-domain-model.md, docs/sprints/sprint-03.md
# decision 1): OVERDUE es derivado (invariante 13), nunca persistido aqui.
RECEIVABLE_STATUSES = frozenset({"OPEN", "PARTIALLY_PAID", "PAID", "VOID"})

# movement_type de Movement (decision 1): tabla unica de aplicaciones, no una
# tabla por tipo. amount siempre >= 0; el signo del efecto sobre el saldo lo
# determina movement_type (REVERSAL resta lo que su reversed_movement_id
# habia sumado).
MOVEMENT_TYPES = frozenset(
    {"PAYMENT", "RETENTION", "DISCOUNT", "CREDIT_NOTE", "REVERSAL"}
)


class Receivable(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cabecera de cartera 1:1 con la factura ``AUTHORIZED`` que la origina.

    Creado exclusivamente por ``workers/receivables.py::handle_invoice_authorized``
    a partir del evento ``invoice.authorized``; no existe endpoint de creacion
    manual (decision 5 de ``docs/sprints/sprint-03.md``).
    """

    __tablename__ = "receivables"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_receivables_tenant_sales_document",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_receivables_tenant_party",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_receivables_tenant_id"),
        # Un receivable por factura: impide que una re-entrega del evento (o
        # un bug futuro) cree un segundo receivable para el mismo documento.
        UniqueConstraint(
            "tenant_id",
            "sales_document_id",
            name="uq_receivables_tenant_sales_document",
        ),
        CheckConstraint("original_amount >= 0", name="ck_receivables_original_amount_non_negative"),
        Index("ix_receivables_tenant_status", "tenant_id", "status"),
        Index("ix_receivables_tenant_party", "tenant_id", "party_id"),
    )

    sales_document_id: Mapped[uuid.UUID]
    party_id: Mapped[uuid.UUID]
    original_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")


class ReceivableInstallment(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Vencimiento de un ``Receivable``.

    La suma de ``amount`` de las cuotas de un receivable siempre es igual a
    ``Receivable.original_amount`` (verificado al crear, ver
    ``workers/receivables.py``). ``sequence`` es 1-based y ordena las cuotas
    dentro de un mismo receivable (``UniqueConstraint`` evita dos cuotas con
    la misma secuencia).
    """

    __tablename__ = "receivable_installments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_receivable_installments_tenant_receivable",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_receivable_installments_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "receivable_id",
            "sequence",
            name="uq_receivable_installments_tenant_receivable_sequence",
        ),
        CheckConstraint("amount >= 0", name="ck_receivable_installments_amount_non_negative"),
        Index("ix_receivable_installments_receivable", "tenant_id", "receivable_id"),
        Index("ix_receivable_installments_due_date", "tenant_id", "due_date"),
    )

    receivable_id: Mapped[uuid.UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class Movement(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Aplicacion sobre una cuota: pago, retencion, descuento, NC o reverso.

    Definido en esta migracion (esquema completo) aunque su escritura llega
    en fases 2/3 del Sprint 3 (``docs/sprints/sprint-03.md`` decisiones 2, 6,
    7). ``amount`` siempre es ``>= 0``: el efecto sobre el saldo lo determina
    ``movement_type``, nunca el signo de la columna. ``installment_id`` es
    obligatorio (nunca se aplica al receivable en bloque) para que el saldo
    por cuota sea siempre reconstruible. ``reversed_movement_id`` solo se usa
    en movimientos ``REVERSAL`` y un movimiento no puede revertirse dos veces
    (``UniqueConstraint``).

    Idempotencia de nota de credito (decision 6, E5-08): una NC AUTHORIZED
    puede distribuirse en varios ``Movement`` ``CREDIT_NOTE`` (uno por cuota
    tocada, mismo ``support_reference`` = ``access_key`` de la NC), asi que la
    unicidad no puede ser ``(tenant_id, movement_type, support_reference)``
    global -- se garantiza por CUOTA
    (``uq_movements_tenant_installment_type_reference``): un reintento del
    evento ``credit_note.authorized`` nunca vuelve a aplicar la misma NC sobre
    la misma cuota. La defensa primaria de idempotencia sigue siendo la
    verificacion explicita en ``services/receivables.py::apply_credit_note``
    (busca cualquier ``Movement`` con ese ``support_reference`` antes de
    aplicar), igual patron que ``SalesDocument.access_key``.
    """

    __tablename__ = "movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_movements_tenant_receivable",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "installment_id"],
            ["receivable_installments.tenant_id", "receivable_installments.id"],
            name="fk_movements_tenant_installment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reversed_movement_id"],
            ["movements.tenant_id", "movements.id"],
            name="fk_movements_tenant_reversed_movement",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_movements_tenant_id"),
        # Un movimiento ya revertido no admite un segundo reverso (decision 7).
        UniqueConstraint(
            "tenant_id",
            "reversed_movement_id",
            name="uq_movements_tenant_reversed_movement",
        ),
        # Idempotencia de NC por cuota (decision 6, ver docstring de la clase).
        UniqueConstraint(
            "tenant_id",
            "installment_id",
            "movement_type",
            "support_reference",
            name="uq_movements_tenant_installment_type_reference",
        ),
        CheckConstraint("amount >= 0", name="ck_movements_amount_non_negative"),
        Index("ix_movements_receivable", "tenant_id", "receivable_id"),
        Index("ix_movements_installment", "tenant_id", "installment_id"),
    )

    receivable_id: Mapped[uuid.UUID]
    installment_id: Mapped[uuid.UUID]
    movement_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    # Texto libre: numero de retencion, motivo de descuento, id/clave de NC.
    support_reference: Mapped[str | None] = mapped_column(String(200))
    reversed_movement_id: Mapped[uuid.UUID | None]
    actor_id: Mapped[str] = mapped_column(String(200))


class CustomerCredit(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Saldo a favor cuando una nota de credito excede el saldo abierto.

    Definido en esta migracion; su escritura llega con E5-08 (aplicacion de
    NC, fase 3 del Sprint 3). ``origin_credit_note_id`` referencia el
    ``SalesDocument`` (``CREDIT_NOTE``) que genero el excedente.
    """

    __tablename__ = "customer_credits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_customer_credits_tenant_party",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "origin_credit_note_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_customer_credits_tenant_origin_credit_note",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_customer_credits_tenant_id"),
        CheckConstraint("amount >= 0", name="ck_customer_credits_amount_non_negative"),
        CheckConstraint(
            "remaining_amount >= 0", name="ck_customer_credits_remaining_amount_non_negative"
        ),
        Index("ix_customer_credits_tenant_party", "tenant_id", "party_id"),
    )

    party_id: Mapped[uuid.UUID]
    origin_credit_note_id: Mapped[uuid.UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class CollectionReminder(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Registro de un recordatorio de cobranza enviado (o stubbeado) a un cliente.

    Creado por ``integrations/notifications/stub.py::StubNotifier`` (fase 1)
    o por implementaciones futuras de ``Notifier``. ``channel`` puede ser
    "email", "sms", "whatsapp", etc. ``template_id`` identifica la plantilla
    usada (ej: "overdue_3_days", "payment_reminder"). ``recipient`` es el
    destino (email para canal email, teléfono para sms).

    ``status`` indica el estado: STUBBED (simulado sin envío real),
    SENT (enviado exitosamente), FAILED (error en el envío).
    La verificación de ``party.consent_opt_out`` es responsabilidad de la
    implementación de ``Notifier`` antes de crear este registro.
    """

    __tablename__ = "collection_reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_collection_reminders_tenant_party",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_collection_reminders_tenant_id"),
        CheckConstraint(
            "status IN ('STUBBED', 'SENT', 'FAILED')",
            name="ck_collection_reminders_status_valid",
        ),
        Index("ix_collection_reminders_tenant_party", "tenant_id", "party_id"),
        Index("ix_collection_reminders_tenant_status", "tenant_id", "status"),
        Index("ix_collection_reminders_created_at", "tenant_id", "created_at"),
    )

    party_id: Mapped[uuid.UUID]
    channel: Mapped[str] = mapped_column(String(50))
    template_id: Mapped[str] = mapped_column(String(100))
    recipient: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="STUBBED")


__all__ = [
    "MOVEMENT_TYPES",
    "RECEIVABLE_STATUSES",
    "CollectionReminder",
    "CustomerCredit",
    "Movement",
    "Receivable",
    "ReceivableInstallment",
]

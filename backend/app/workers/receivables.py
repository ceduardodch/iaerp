"""Consumidores de eventos del contexto Receivables (E5-01/E5-02, E5-08).

``invoice.authorized`` crea la cartera (ver ``handle_invoice_authorized``).
``credit_note.authorized`` (Sprint 3 Fase 2) aplica la NC autorizada contra
el receivable de su factura relacionada (ver
``handle_credit_note_authorized``), documentado mas abajo.

``docs/sprints/sprint-03.md`` decision 5: la unica forma de crear un
``Receivable`` es este handler, disparado por el evento de dominio
``invoice.authorized`` que ``workers/sri_transmission.py`` publica de forma
aditiva cuando una ``INVOICE`` transiciona a ``AUTHORIZED``. No existe
``POST /receivables`` de creacion manual.

Flujo:

1. Recarga el ``SalesDocument`` (siempre desde ``sales_document_id``, nunca
   confia en el payload del evento para los montos) y confirma que sigue
   ``AUTHORIZED`` y es ``INVOICE``.
2. IDEMPOTENTE: si ya existe un ``Receivable`` para ese
   ``sales_document_id`` (``UniqueConstraint`` + verificacion explicita), no
   crea un segundo. Cubre tanto la dedupe de ``consume_once``
   (``InboxEvent`` por ``consumer_name``/``event_id``) como una re-entrega
   con un ``event_id`` distinto (defensa en profundidad, igual que
   ``SalesDocument.access_key`` en Sprint 2).
3. ``original_amount`` = ``SalesDocument.total`` (nunca recalculado: la
   factura ya es la fuente de verdad fiscal, ADR 0004). ``party_id`` = el
   cliente de la factura.
4. Las cuotas provienen de ``SalesDocumentInstallment`` (Sprint 3 Fase 2,
   ``services/billing.py::create_invoice_draft`` las persiste tal como
   llegaron en ``InvoiceInput.installments``, validando que su suma sea
   exactamente el total). Si el documento no tiene cuotas persistidas
   (defensa para datos de una fase anterior o un documento migrado sin
   plan de pago), se cae a una cuota unica de contado por el total con
   ``due_date = issue_date``, que es el comportamiento declarado en la
   decision 5 para "installments con una sola cuota igual al total".
5. Audita ``receivable.created`` con ``append_audit`` bajo un
   ``AuthContext`` de sistema (``actor_type="SYSTEM"``): este handler corre
   fuera de una request HTTP autenticada, igual que el resto de
   ``workers/sri_transmission.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import DocumentRelation, SalesDocument, SalesDocumentInstallment
from app.models.receivables import Receivable, ReceivableInstallment
from app.services.receivables import apply_credit_note, lock_receivable
from app.services.unit_of_work import append_audit
from app.workers.outbox import OutboxMessage

CONSUMER_NAME = "iaerp.receivables"

_SYSTEM_ACTOR_ID = "system:invoice-authorized-consumer"
_CREDIT_NOTE_SYSTEM_ACTOR_ID = "system:credit-note-authorized-consumer"


def _system_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        actor_id=_SYSTEM_ACTOR_ID,
        actor_type="SYSTEM",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset(),
        token_id="",
    )


async def _existing_receivable(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sales_document_id: uuid.UUID,
) -> Receivable | None:
    result: Receivable | None = await session.scalar(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.sales_document_id == sales_document_id,
        )
    )
    return result


async def _load_document_installments(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> list[SalesDocumentInstallment]:
    return list(
        (
            await session.scalars(
                select(SalesDocumentInstallment)
                .where(
                    SalesDocumentInstallment.tenant_id == tenant_id,
                    SalesDocumentInstallment.sales_document_id == document_id,
                )
                .order_by(SalesDocumentInstallment.sequence)
            )
        ).all()
    )


async def _build_installments(
    session: AsyncSession, document: SalesDocument
) -> list[tuple[int, date, Decimal]]:
    """Cuotas reales del documento, con fallback a cuota unica de contado.

    Ver docstring del modulo, punto 4. Devuelve tripletas
    ``(sequence, due_date, amount)`` cuya suma es siempre igual a
    ``document.total`` -- verificado por el llamador.
    """

    persisted = await _load_document_installments(
        session, tenant_id=document.tenant_id, document_id=document.id
    )
    if persisted:
        return [
            (installment.sequence, installment.due_date, installment.amount)
            for installment in persisted
        ]
    return [(1, document.issue_date, document.total)]


async def handle_invoice_authorized(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    """Handler del evento ``invoice.authorized`` (registrado en ``workers/tasks.py``)."""

    tenant_id = message.tenant_id
    document_id = uuid.UUID(message.aggregate_id)

    document = await session.get(SalesDocument, document_id)
    if document is None or document.tenant_id != tenant_id:
        # Documento inexistente o de otro tenant: nada que materializar.
        return
    if document.document_type != "INVOICE" or document.status != "AUTHORIZED":
        # Evento fuera de orden, o el documento cambio de estado entre la
        # publicacion y el consumo (no deberia ocurrir: AUTHORIZED es
        # terminal positivo, ver docs/03-domain-model.md); no hay nada seguro
        # que crear.
        return

    existing = await _existing_receivable(
        session, tenant_id=tenant_id, sales_document_id=document.id
    )
    if existing is not None:
        # Idempotente: una re-entrega del evento (id de evento distinto, o un
        # reintento que ya paso por consume_once en otra ejecucion) nunca crea
        # un segundo receivable para la misma factura.
        return

    installments = await _build_installments(session, document)
    installment_total = sum((amount for _, _, amount in installments), Decimal("0.00"))
    if installment_total != document.total:
        # Defensa: nunca deberia ocurrir con _build_installments actual (una
        # sola cuota == total), pero protege contra una futura extension que
        # rompa el invariante 11 del dominio ("cuotas... suman exactamente el
        # monto original").
        raise ValueError(
            "Receivable installments must sum exactly to the invoice total: "
            f"expected {document.total}, got {installment_total}"
        )

    receivable = Receivable(
        tenant_id=tenant_id,
        sales_document_id=document.id,
        party_id=document.party_id,
        original_amount=document.total,
        currency=document.currency,
        status="OPEN",
    )
    session.add(receivable)
    await session.flush()

    for sequence, due_date, amount in installments:
        session.add(
            ReceivableInstallment(
                tenant_id=tenant_id,
                receivable_id=receivable.id,
                sequence=sequence,
                due_date=due_date,
                amount=amount,
            )
        )
    await session.flush()

    await append_audit(
        session,
        context=_system_context(tenant_id),
        action="receivable.created",
        entity_type="receivable",
        entity_id=str(receivable.id),
        correlation_id=message.correlation_id,
        idempotency_key=f"invoice-authorized:{document.id}",
        details={
            "sales_document_id": str(document.id),
            "original_amount": str(document.total),
            "installment_count": len(installments),
        },
    )


async def _related_invoice_id(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    credit_note_id: uuid.UUID,
) -> uuid.UUID | None:
    relation = await session.scalar(
        select(DocumentRelation).where(
            DocumentRelation.tenant_id == tenant_id,
            DocumentRelation.credit_note_id == credit_note_id,
        )
    )
    return relation.related_invoice_id if relation is not None else None


async def handle_credit_note_authorized(
    session: AsyncSession,
    message: OutboxMessage,
) -> None:
    """Handler del evento ``credit_note.authorized`` (E5-08, decision 6).

    Flujo:

    1. Recarga la NC (siempre desde ``sales_document_id``, nunca confia en el
       payload) y confirma que sigue ``AUTHORIZED`` y es ``CREDIT_NOTE``.
    2. Resuelve la factura relacionada via ``DocumentRelation`` (creada por
       ``services/billing.py::create_credit_note``) y su ``Receivable``; si
       cualquiera falta, no hay cartera contra la cual aplicar (no deberia
       ocurrir para una NC ya autorizada, pero es una salida segura, no un
       error fatal).
    3. ``lock_receivable`` (mismo lock que ``record_payment``) antes de
       aplicar, para serializar contra cualquier cobro concurrente sobre el
       mismo receivable.
    4. ``services/receivables.py::apply_credit_note`` distribuye el ``total``
       de la NC contra las cuotas abiertas (mas antigua primero) y crea
       ``CustomerCredit`` con el excedente; es idempotente por
       ``access_key`` de la NC (verificacion explicita antes de aplicar,
       ``UniqueConstraint`` por cuota como defensa adicional).
    5. Audita ``receivable.credit_note_applied``.
    """

    tenant_id = message.tenant_id
    credit_note_id = uuid.UUID(message.aggregate_id)

    credit_note = await session.get(SalesDocument, credit_note_id)
    if credit_note is None or credit_note.tenant_id != tenant_id:
        return
    if credit_note.document_type != "CREDIT_NOTE" or credit_note.status != "AUTHORIZED":
        return
    if credit_note.access_key is None:
        # Defensa: una NC AUTHORIZED siempre tiene access_key; sin ella no hay
        # forma segura de garantizar idempotencia.
        return

    invoice_id = await _related_invoice_id(
        session, tenant_id=tenant_id, credit_note_id=credit_note.id
    )
    if invoice_id is None:
        return

    receivable = await session.scalar(
        select(Receivable).where(
            Receivable.tenant_id == tenant_id,
            Receivable.sales_document_id == invoice_id,
        )
    )
    if receivable is None:
        # La factura de sustento no tiene receivable propio (no deberia
        # ocurrir para una INVOICE AUTHORIZED, ver decision 5); nada seguro
        # que aplicar todavia.
        return

    locked_receivable = await lock_receivable(
        session, tenant_id=tenant_id, receivable_id=receivable.id
    )
    if locked_receivable is None:
        return

    movement = await apply_credit_note(
        session,
        tenant_id=tenant_id,
        receivable=locked_receivable,
        credit_note_total=credit_note.total,
        credit_note_access_key=credit_note.access_key,
        party_id=locked_receivable.party_id,
        origin_credit_note_id=credit_note.id,
        actor_id=_CREDIT_NOTE_SYSTEM_ACTOR_ID,
    )
    if movement is None:
        # Ya aplicada (idempotencia) o total <= 0: nada nuevo que auditar.
        return

    await append_audit(
        session,
        context=_system_context(tenant_id),
        action="receivable.credit_note_applied",
        entity_type="receivable",
        entity_id=str(locked_receivable.id),
        correlation_id=message.correlation_id,
        idempotency_key=f"credit-note-authorized:{credit_note.id}",
        details={
            "credit_note_id": str(credit_note.id),
            "credit_note_access_key": credit_note.access_key,
            "credit_note_total": str(credit_note.total),
            "receivable_id": str(locked_receivable.id),
        },
    )


__all__ = [
    "CONSUMER_NAME",
    "handle_credit_note_authorized",
    "handle_invoice_authorized",
]

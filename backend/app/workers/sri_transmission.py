"""Consumidor del evento ``invoice.signed``: transmision SRI y reconciliacion.

Flujo (E4-04/E4-05/E4-08, ``docs/sprints/sprint-02.md`` decisiones 3 y 8):

1. Carga el ``SalesDocument`` y sus ``SRITransmission`` previas por
   ``access_key``.
2. Reconciliacion (E4-05): si ya existe una transmision en ``RECEIVED``,
   ``PENDING_AUTHORIZATION`` o ``AUTHORIZED`` para esa clave, NUNCA se vuelve
   a llamar ``send_reception``; solo se llama ``check_authorization``.
3. En caso contrario (primera vez, o reintento tras ``FAILED``), llama
   ``send_reception`` y registra el intento.
4. Segun la respuesta: ``RECEIVED`` agenda la consulta de autorizacion (queda
   ``PENDING_AUTHORIZATION``, el documento pasa a ``RECEIVED``);
   ``RETURNED`` marca ``REJECTED`` (terminal, no se reintenta: es un rechazo
   fiscal, no un error tecnico); ``AUTHORIZED``/``NOT_AUTHORIZED`` actualizan
   el documento directamente.
5. Un fallo TECNICO (``TimeoutError`` del cliente SRI, o cualquier excepcion
   no fiscal) reprograma el propio ``OutboxEvent`` con backoff
   (``workers/outbox.retry_delay``) hasta agotar ``OUTBOX_MAX_ATTEMPTS``, en
   cuyo caso crea un ``DeadLetter`` conservando el vinculo con el
   ``SalesDocument`` de origen. Este handler nunca deja que la excepcion
   escape hacia ``consume_once``: si lo hiciera, el ``InboxEvent`` no se
   completaria pero el ``OutboxEvent`` ya fue marcado publicado por el
   dispatcher (ver ``workers/outbox.dispatch_outbox_once``), perdiendo el
   reintento. Reprogramar el outbox explicitamente es la unica forma de
   reintentar con este disenio de outbox/dispatcher/Celery.
6. Sprint 3 (decision 5, cambio aditivo): cuando una ``INVOICE`` transiciona
   REALMENTE a ``AUTHORIZED`` (nunca lo estaba antes), este handler tambien
   publica un ``OutboxEvent`` ``invoice.authorized`` en la MISMA transaccion
   (ver ``_publish_invoice_authorized``). No se publica de nuevo si el
   documento ya estaba ``AUTHORIZED`` (reconciliacion/reintento del propio
   ``invoice.signed``), y una nota de credito nunca lo publica (solo
   ``document_type == "INVOICE"``). El resto del flujo de
   ``invoice.signed`` (reintentos, dead-letter, reconciliacion) no cambia.
7. Sprint 3 Fase 2 (decision 6, cambio aditivo simetrico al punto 6): cuando
   una ``CREDIT_NOTE`` transiciona REALMENTE a ``AUTHORIZED``, este handler
   publica ``credit_note.authorized`` en la MISMA transaccion (ver
   ``_publish_credit_note_authorized``), consumido por
   ``workers/receivables.py::handle_credit_note_authorized`` para aplicar la
   NC contra la cartera de su factura relacionada. Simetrico a
   ``invoice.authorized``: solo se publica en la transicion real, nunca en
   una reconciliacion sobre un documento ya ``AUTHORIZED``, y una factura
   nunca lo publica (solo ``document_type == "CREDIT_NOTE"``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.sri.protocol import (
    AuthorizationResult,
    ReceptionResult,
    SRIClient,
)
from app.integrations.sri.simulator import SimulatorSRIClient
from app.integrations.sri.soap import SoapSRIClient
from app.models.billing import DocumentArtifact, SalesDocument, SRITransmission
from app.models.platform import DeadLetter, OutboxEvent
from app.services import storage
from app.workers.outbox import OutboxMessage, retry_delay

settings = get_settings()

CONSUMER_NAME = "iaerp.sri_transmission"

# Evento de dominio nuevo (Sprint 3, decision 5): publicado de forma aditiva
# cuando una INVOICE transiciona a AUTHORIZED; consumido por
# workers/receivables.py::handle_invoice_authorized para crear el Receivable.
INVOICE_AUTHORIZED_EVENT = "invoice.authorized"

# Evento de dominio nuevo (Sprint 3 Fase 2, decision 6): publicado de forma
# aditiva cuando una CREDIT_NOTE transiciona a AUTHORIZED; consumido por
# workers/receivables.py::handle_credit_note_authorized para aplicar la NC
# contra la cartera de su factura relacionada.
CREDIT_NOTE_AUTHORIZED_EVENT = "credit_note.authorized"

# Estados de SRITransmission que indican que la clave ya fue aceptada por el
# SRI/simulador: retransmitirla violaria la regla E4-05 de reconciliacion.
_ALREADY_TRANSMITTED_STATUSES = frozenset(
    {"RECEIVED", "PENDING_AUTHORIZATION", "AUTHORIZED"}
)


def _default_sri_client() -> SRIClient:
    # `soap` = cliente real contra los web services del SRI (celcer/cel segun
    # SRI_ENVIRONMENT); `simulator` = in-process para dev/test. La reconciliacion
    # y los reintentos viven en este worker, sin importar la implementacion.
    if settings.SRI_TRANSMISSION_MODE == "soap":
        return SoapSRIClient(
            environment=settings.SRI_ENVIRONMENT,
            reception_url=settings.SRI_RECEPTION_URL,
            authorization_url=settings.SRI_AUTHORIZATION_URL,
            timeout=settings.SRI_HTTP_TIMEOUT,
        )
    return SimulatorSRIClient()


def _message_entries(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in messages]


async def _load_signed_xml(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> bytes:
    """Descarga el XML firmado desde MinIO usando el ``DocumentArtifact`` persistido.

    ``issue_document`` (``services/billing.py``) siempre sube el XML firmado
    ANTES de que el evento ``invoice.signed`` se publique (misma
    transaccion), asi que el artefacto existe cuando este handler corre.
    """

    artifact = await session.scalar(
        select(DocumentArtifact)
        .where(
            DocumentArtifact.tenant_id == tenant_id,
            DocumentArtifact.sales_document_id == document_id,
            DocumentArtifact.artifact_type == "xml-signed",
        )
        .order_by(DocumentArtifact.version.desc())
        .limit(1)
    )
    if artifact is None:
        raise ValueError(f"No signed XML artifact found for document {document_id}")
    return await storage.download_artifact(object_key=artifact.object_key)


async def _latest_transmission_for_access_key(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    access_key: str,
) -> SRITransmission | None:
    transmission: SRITransmission | None = await session.scalar(
        select(SRITransmission)
        .where(
            SRITransmission.tenant_id == tenant_id,
            SRITransmission.access_key == access_key,
        )
        .order_by(SRITransmission.created_at.desc())
        .limit(1)
    )
    return transmission


async def _transmission_event_count(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> int:
    """Cuenta cuantos eventos ``invoice.signed`` existen para el documento.

    El primero lo emite ``issue_document``; cada re-consulta agenda uno nuevo.
    Sirve como contador de intentos para el backoff y el tope de reintentos,
    sin depender del ``OutboxEvent`` original (que ya quedo consumido por su
    ``InboxEvent`` y no puede reprocesarse).
    """

    count = await session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.aggregate_id == str(document_id),
            OutboxEvent.event_type == "invoice.signed",
        )
    )
    return int(count or 0)


async def _enqueue_followup(
    session: AsyncSession,
    *,
    message: OutboxMessage,
    delay: timedelta,
) -> None:
    """Encola un ``OutboxEvent`` FRESCO para re-consultar autorizacion mas tarde.

    Se usa un evento nuevo (id propio) a proposito: reabrir el evento original
    no funciona porque su ``InboxEvent`` ya esta ``COMPLETED`` y
    ``consume_once`` lo deduplicaria. Un id nuevo produce un ``InboxEvent``
    nuevo, de modo que el handler vuelve a correr y toma la via de
    reconciliacion (nunca retransmite; solo consulta autorizacion).
    """

    now = datetime.now(UTC)
    session.add(
        OutboxEvent(
            tenant_id=message.tenant_id,
            event_type="invoice.signed",
            aggregate_type=message.aggregate_type,
            aggregate_id=message.aggregate_id,
            payload=dict(message.payload),
            correlation_id=message.correlation_id,
            attempts=0,
            available_at=now + delay,
            published_at=None,
            lease_until=None,
        )
    )


async def _dead_letter(
    session: AsyncSession,
    *,
    message: OutboxMessage,
    document: SalesDocument,
    error: str,
    attempts: int,
) -> None:
    """Crea un ``DeadLetter`` conservando el vinculo con el documento de origen."""

    session.add(
        DeadLetter(
            tenant_id=message.tenant_id,
            source_type="OUTBOX",
            source_id=message.event_id,
            event_type="invoice.signed",
            payload={
                "aggregate_type": message.aggregate_type,
                "aggregate_id": message.aggregate_id,
                "correlation_id": message.correlation_id,
                "sales_document_id": str(document.id),
                "access_key": document.access_key,
            },
            error=error[:1000],
            attempts=attempts,
        )
    )


async def _followup_or_dead_letter(
    session: AsyncSession,
    *,
    message: OutboxMessage,
    document: SalesDocument,
    error: str | None,
) -> None:
    """Agenda una nueva pasada del handler con backoff, o crea dead letter al tope.

    Se invoca cuando el documento quedo en un estado NO terminal
    (``RECEIVED``/``PENDING_AUTHORIZATION``) o ante un fallo tecnico. Reutiliza
    ``retry_delay`` (misma formula que el resto del sistema) y
    ``OUTBOX_MAX_ATTEMPTS`` como tope.
    """

    attempts = await _transmission_event_count(
        session, tenant_id=message.tenant_id, document_id=document.id
    )
    if attempts >= settings.OUTBOX_MAX_ATTEMPTS:
        await _dead_letter(
            session,
            message=message,
            document=document,
            error=error or "SRI authorization did not resolve within retry budget",
            attempts=attempts,
        )
        return
    await _enqueue_followup(session, message=message, delay=retry_delay(attempts))


async def _record_transmission_attempt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
    status: str,
    messages: list[dict[str, str]],
    authorization_number: str | None = None,
    authorized_at: datetime | None = None,
) -> SRITransmission:
    assert document.access_key is not None  # noqa: S101 - guaranteed by caller (SIGNED document)
    transmission = await _latest_transmission_for_access_key(
        session, tenant_id=tenant_id, access_key=document.access_key
    )
    if transmission is None:
        transmission = SRITransmission(
            tenant_id=tenant_id,
            sales_document_id=document.id,
            access_key=document.access_key,
            status=status,
            messages=[],
            attempts=0,
        )
        session.add(transmission)

    transmission.status = status
    transmission.attempts += 1
    transmission.messages = [*transmission.messages, *_message_entries(messages)]
    if authorization_number is not None:
        transmission.authorization_number = authorization_number
    if authorized_at is not None:
        transmission.authorized_at = authorized_at
    await session.flush()
    return transmission


async def _apply_reception_result(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
    result: ReceptionResult,
) -> None:
    if result.status == "RECEIVED":
        await _record_transmission_attempt(
            session,
            tenant_id=tenant_id,
            document=document,
            status="RECEIVED",
            messages=result.messages,
        )
        document.status = "RECEIVED"
    else:  # RETURNED: rechazo fiscal temprano, terminal, no reintentable.
        await _record_transmission_attempt(
            session,
            tenant_id=tenant_id,
            document=document,
            status="REJECTED",
            messages=result.messages,
        )
        document.status = "REJECTED"
    await session.flush()


async def _publish_invoice_authorized(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
) -> None:
    """Publica ``invoice.authorized`` en la MISMA transaccion que autoriza el documento.

    Cambio aditivo (``docs/sprints/sprint-03.md`` decision 5): no altera el
    camino de reintentos/dead-letter/reconciliacion de ``invoice.signed`` (ese
    outbox y su ``event_type`` siguen intactos); solo agrega un
    ``OutboxEvent`` nuevo con su propio ``event_type`` para que
    ``workers/receivables.py::handle_invoice_authorized`` cree la cartera.
    Payload minimo (``sales_document_id``/``tenant_id``/``access_key``): el
    handler siempre puede recargar el documento completo desde
    ``sales_document_id``, igual que el resto de handlers de este modulo.
    """

    session.add(
        OutboxEvent(
            tenant_id=tenant_id,
            event_type=INVOICE_AUTHORIZED_EVENT,
            aggregate_type="sales_document",
            aggregate_id=str(document.id),
            payload={
                "sales_document_id": str(document.id),
                "tenant_id": str(tenant_id),
                "access_key": document.access_key,
            },
            correlation_id=str(uuid.uuid4()),
            available_at=datetime.now(UTC),
        )
    )


async def _publish_credit_note_authorized(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
) -> None:
    """Publica ``credit_note.authorized`` en la MISMA transaccion que autoriza la NC.

    Simetrico a ``_publish_invoice_authorized`` (Sprint 3 Fase 2, decision 6):
    cambio aditivo, no altera el camino de reintentos/dead-letter/
    reconciliacion de ``invoice.signed``. Payload minimo -- el handler
    siempre recarga el ``SalesDocument`` completo desde ``sales_document_id``.
    """

    session.add(
        OutboxEvent(
            tenant_id=tenant_id,
            event_type=CREDIT_NOTE_AUTHORIZED_EVENT,
            aggregate_type="sales_document",
            aggregate_id=str(document.id),
            payload={
                "sales_document_id": str(document.id),
                "tenant_id": str(tenant_id),
                "access_key": document.access_key,
            },
            correlation_id=str(uuid.uuid4()),
            available_at=datetime.now(UTC),
        )
    )


async def _apply_authorization_result(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
    result: AuthorizationResult,
) -> None:
    if result.status == "AUTHORIZED":
        # Capturado ANTES de mutar document.status: solo la transicion REAL
        # hacia AUTHORIZED (nunca ya estaba AUTHORIZED) publica el evento, asi
        # que una re-consulta de reconciliacion sobre un documento ya
        # autorizado (ver test_duplicate_response_scenario_...) nunca lo
        # publica dos veces.
        was_already_authorized = document.status == "AUTHORIZED"
        await _record_transmission_attempt(
            session,
            tenant_id=tenant_id,
            document=document,
            status="AUTHORIZED",
            messages=result.messages,
            authorization_number=result.authorization_number,
            authorized_at=result.authorized_at,
        )
        document.status = "AUTHORIZED"
        document.authorization_number = result.authorization_number
        document.authorized_at = result.authorized_at
        if (
            document.document_type == "INVOICE"
            and not was_already_authorized
        ):
            await _publish_invoice_authorized(
                session, tenant_id=tenant_id, document=document
            )
        elif (
            document.document_type == "CREDIT_NOTE"
            and not was_already_authorized
        ):
            await _publish_credit_note_authorized(
                session, tenant_id=tenant_id, document=document
            )
    elif result.status == "NOT_AUTHORIZED":
        await _record_transmission_attempt(
            session,
            tenant_id=tenant_id,
            document=document,
            status="NOT_AUTHORIZED",
            messages=result.messages,
        )
        document.status = "NOT_AUTHORIZED"
    else:  # PENDING_AUTHORIZATION: sigue en curso, no es un fallo.
        await _record_transmission_attempt(
            session,
            tenant_id=tenant_id,
            document=document,
            status="PENDING_AUTHORIZATION",
            messages=result.messages,
        )
        document.status = "PENDING_AUTHORIZATION"
    await session.flush()


async def handle_invoice_signed(
    session: AsyncSession,
    message: OutboxMessage,
    *,
    sri_client: SRIClient | None = None,
) -> None:
    """Handler del evento ``invoice.signed`` (registrado en ``workers/tasks.py``).

    Nunca deja escapar una excepcion: los fallos tecnicos se resuelven
    reprogramando el ``OutboxEvent`` de origen (ver
    ``_reschedule_or_dead_letter``) para no perder el mecanismo de reintento.
    """

    client = sri_client or _default_sri_client()
    tenant_id = message.tenant_id
    document_id = uuid.UUID(message.aggregate_id)

    document = await session.get(SalesDocument, document_id)
    if document is None or document.tenant_id != tenant_id:
        # El documento no existe o no pertenece a este tenant: nada que
        # transmitir. No es un fallo tecnico, no se reintenta.
        return
    if document.access_key is None:
        # Un documento SIGNED siempre tiene access_key; si no la tiene, el
        # evento llego fuera de orden o el documento nunca se firmo. No hay
        # nada seguro que transmitir todavia.
        return

    try:
        existing = await _latest_transmission_for_access_key(
            session, tenant_id=tenant_id, access_key=document.access_key
        )
        if existing is not None and existing.status in _ALREADY_TRANSMITTED_STATUSES:
            # Regla E4-05: reconciliar, nunca retransmitir una clave ya
            # aceptada por el SRI/simulador.
            authorization = await client.check_authorization(document.access_key)
            await _apply_authorization_result(
                session,
                tenant_id=tenant_id,
                document=document,
                result=authorization,
            )
        else:
            signed_xml = await _load_signed_xml(
                session, tenant_id=tenant_id, document_id=document.id
            )
            reception = await client.send_reception(signed_xml, document.access_key)
            await _apply_reception_result(
                session,
                tenant_id=tenant_id,
                document=document,
                result=reception,
            )
            if reception.status == "RECEIVED":
                authorization = await client.check_authorization(document.access_key)
                await _apply_authorization_result(
                    session,
                    tenant_id=tenant_id,
                    document=document,
                    result=authorization,
                )
    except Exception as exc:  # noqa: BLE001 - fallo tecnico, se reprograma explicitamente
        await _followup_or_dead_letter(
            session,
            message=message,
            document=document,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    # Si el documento sigue en un estado no terminal (recepcion aceptada pero
    # autorizacion todavia PENDING), agenda una nueva consulta con backoff. Un
    # evento fresco evita la deduplicacion del InboxEvent del evento actual.
    if document.status in {"RECEIVED", "PENDING_AUTHORIZATION"}:
        await _followup_or_dead_letter(
            session,
            message=message,
            document=document,
            error=None,
        )


__all__ = [
    "CONSUMER_NAME",
    "CREDIT_NOTE_AUTHORIZED_EVENT",
    "INVOICE_AUTHORIZED_EVENT",
    "handle_invoice_signed",
]

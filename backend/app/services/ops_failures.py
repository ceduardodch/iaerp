"""Lectura de fallos operativos terminales para la bandeja de incidencias.

``dead_letters`` es la fuente canonica y COMPLETA de fallos terminales, y por
eso este servicio no consulta ninguna otra tabla:

- El dispatcher (``workers/outbox.py::_mark_failed``) marca
  ``dead_lettered_at`` en el ``OutboxEvent`` *y ademas* inserta la fila de
  ``DeadLetter``.
- El consumidor SRI (``workers/sri_transmission.py::_followup_or_dead_letter``)
  solo inserta la fila de ``DeadLetter``, porque el dispatcher ya dio por
  publicado su ``OutboxEvent``.

Unir ambas tablas duplicaria todos los fallos del primer camino. El
``UniqueConstraint(source_type, source_id)`` de ``dead_letters`` ya garantiza
una sola fila por fallo.

Un rechazo fiscal del SRI NUNCA llega aqui: ``sri_transmission`` lo trata como
terminal (``RETURNED`` -> ``REJECTED``) sin pasar por dead letter. Lo que se ve
en esta bandeja son fallos tecnicos que agotaron su presupuesto de reintentos.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import DeadLetter, OutboxEvent
from app.schemas.platform import OpsFailureRead

FailureClassification = Literal["AUTO_RETRY", "NEEDS_HUMAN"]

# Lista blanca explicita y de default-deny (pendiente 3,
# docs/OBSERVABILIDAD_PENDIENTES.md): un event_type solo entra aqui cuando su
# handler demuestra reconciliacion idempotente, es decir que reintentarlo no
# puede duplicar un efecto ya producido.
#
# "invoice.signed" es el unico caso hoy: antes de retransmitir,
# workers/sri_transmission.py::handle_invoice_signed consulta la ultima
# SRITransmission de la clave de acceso y, si ya esta RECEIVED,
# PENDING_AUTHORIZATION o AUTHORIZED (_ALREADY_TRANSMITTED_STATUSES), NUNCA
# vuelve a llamar send_reception: solo reconsulta autorizacion. Es la misma
# ruta que ya usa el propio backoff automatico antes de agotar
# OUTBOX_MAX_ATTEMPTS, asi que reintentarlo de nuevo tras el dead letter no es
# un caso nuevo, es repetir un camino ya probado en produccion.
#
# Ningun otro event_type (invoice.authorized, credit_note.authorized,
# collection.reminder.due, campaign.*, tax.xml_recovery.requested, ...) tiene
# ese chequeo: sus handlers no verifican si el efecto (crear un Receivable,
# aplicar una NC, enviar un recordatorio, publicar una campaña) ya ocurrio
# antes de repetirlo. Agregar uno aqui sin esa reconciliacion permitiria a un
# agente duplicar un efecto de negocio ya producido.
_AUTO_RETRY_EVENT_TYPES: frozenset[str] = frozenset({"invoice.signed"})


def classify_failure(event_type: str) -> FailureClassification:
    """Decide si un fallo dead-letterado puede reintentarse solo o no.

    Default deny: cualquier ``event_type`` fuera de la lista blanca es
    ``NEEDS_HUMAN``, incluidos los desconocidos.
    """

    if event_type in _AUTO_RETRY_EVENT_TYPES:
        return "AUTO_RETRY"
    return "NEEDS_HUMAN"


def _payload_text(payload: dict[str, Any] | None, key: str) -> str | None:
    """Lee una clave del ``payload`` sin asumir su forma.

    El payload lo escriben los workers y su contenido varia por ``event_type``;
    una clave ausente o no textual no debe romper el listado completo.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _to_read(entity: DeadLetter) -> OpsFailureRead:
    return OpsFailureRead(
        id=entity.id,
        source_type=entity.source_type,
        source_id=entity.source_id,
        event_type=entity.event_type,
        error=entity.error,
        attempts=entity.attempts,
        status=entity.status,
        correlation_id=_payload_text(entity.payload, "correlation_id"),
        aggregate_type=_payload_text(entity.payload, "aggregate_type"),
        aggregate_id=_payload_text(entity.payload, "aggregate_id"),
        created_at=entity.created_at,
        resolved_at=entity.resolved_at,
    )


async def list_failures(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[OpsFailureRead]:
    query = select(DeadLetter).where(DeadLetter.tenant_id == tenant_id)
    if status is not None:
        query = query.where(DeadLetter.status == status)
    if since is not None:
        query = query.where(DeadLetter.created_at >= since)
    query = query.order_by(DeadLetter.created_at.desc()).limit(limit).offset(offset)

    entities = (await session.scalars(query)).all()
    return [_to_read(entity) for entity in entities]


async def retry_failure(
    session: AsyncSession,
    context: AuthContext,
    failure_id: uuid.UUID,
) -> OpsFailureRead:
    """Reintento MANUAL de un fallo `dead_lettered`, disparado por un humano.

    A diferencia del futuro agente de la Fase 3 (``ops.retry_failure``,
    pendiente 11), este endpoint no pasa por ``classify_failure()``: un
    humano ya ejerció su propio juicio al pedir el reintento. Solo exige que
    el fallo siga ``OPEN`` y sea del tenant del actor.

    Encola un ``OutboxEvent`` FRESCO (id nuevo) en vez de reabrir el
    original, igual que ``workers/sri_transmission.py::_enqueue_followup``:
    reabrir el evento original no sirve porque su ``InboxEvent`` puede seguir
    ``COMPLETED`` y ``consume_once`` lo deduplicaría.
    """

    entity = await session.scalar(
        select(DeadLetter)
        .where(
            DeadLetter.id == failure_id,
            DeadLetter.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Ops failure not found")
    if entity.status != "OPEN":
        raise HTTPException(
            status_code=409,
            detail="Ops failure is not open; it was already resolved",
        )

    aggregate_type = _payload_text(entity.payload, "aggregate_type")
    aggregate_id = _payload_text(entity.payload, "aggregate_id")
    if not aggregate_type or not aggregate_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ops failure payload is missing aggregate_type/aggregate_id; "
                "cannot retry"
            ),
        )
    correlation_id = _payload_text(entity.payload, "correlation_id") or str(uuid.uuid4())

    now = datetime.now(UTC)
    session.add(
        OutboxEvent(
            tenant_id=entity.tenant_id,
            event_type=entity.event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=dict(entity.payload),
            correlation_id=correlation_id,
            attempts=0,
            available_at=now,
            published_at=None,
            lease_until=None,
        )
    )
    entity.status = "RESOLVED"
    entity.resolved_at = now
    await session.flush()
    return _to_read(entity)

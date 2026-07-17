import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.platform import AuditEvent, IdempotencyRecord, OutboxEvent, Tenant


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


async def append_audit(
    session: AsyncSession,
    *,
    context: AuthContext,
    action: str,
    entity_type: str,
    entity_id: str | None,
    correlation_id: str,
    idempotency_key: str,
    details: dict[str, Any],
) -> None:
    previous = await session.scalar(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == context.tenant_id)
        .order_by(AuditEvent.sequence.desc())
        .limit(1)
    )
    previous_hash = previous.event_hash if previous else None
    sequence = previous.sequence + 1 if previous else 1
    hash_payload = {
        "tenant_id": str(context.tenant_id),
        "actor_id": context.actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "details": details,
        "previous_hash": previous_hash,
        "sequence": sequence,
    }
    session.add(
        AuditEvent(
            tenant_id=context.tenant_id,
            sequence=sequence,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            decision="ALLOWED",
            details=details,
            previous_hash=previous_hash,
            event_hash=canonical_hash(hash_payload),
        )
    )


async def execute_idempotent(
    session: AsyncSession,
    *,
    context: AuthContext,
    operation: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
    action: str,
    entity_type: str,
    callback: Callable[[], Awaitable[tuple[str, dict[str, Any]]]],
    event_type: str | None = None,
) -> dict[str, Any]:
    request_hash = canonical_hash(request_payload)
    correlation_id = str(uuid.uuid4())

    # Authentication performs read-only queries and may leave an implicit
    # transaction open. Start the mutation with a clean Unit of Work.
    if session.in_transaction():
        await session.rollback()

    async with session.begin():
        # Lock before inserting any tenant child row. Acquiring this later can
        # deadlock with concurrent foreign-key key-share locks in PostgreSQL.
        await session.scalar(
            select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update()
        )
        existing = await session.scalar(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.tenant_id == context.tenant_id,
                IdempotencyRecord.actor_id == context.actor_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was used with a different request",
                )
            if existing.status == "COMPLETED" and existing.response_body is not None:
                return existing.response_body
            raise HTTPException(status_code=409, detail="Operation is already processing")

        record = IdempotencyRecord(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status="PROCESSING",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(record)
        await session.flush()

        entity_id, response = await callback()
        await append_audit(
            session,
            context=context,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            details={"request_hash": request_hash},
        )
        session.add(
            OutboxEvent(
                tenant_id=context.tenant_id,
                event_type=event_type or action,
                aggregate_type=entity_type,
                aggregate_id=entity_id,
                payload={"entity_id": entity_id, "action": action},
                correlation_id=correlation_id,
                available_at=datetime.now(UTC),
            )
        )
        record.status = "COMPLETED"
        record.response_status = 201
        record.response_body = response
        await session.flush()
        return response

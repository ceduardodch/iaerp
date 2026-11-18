"""Read an actor's completed draft request without reissuing a write."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import SalesDocument
from app.models.platform import IdempotencyRecord


async def find_completed_draft_request(
    session: AsyncSession, context: AuthContext, idempotency_key: str
) -> uuid.UUID:
    record = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == context.tenant_id,
            IdempotencyRecord.actor_id == context.actor_id,
            IdempotencyRecord.operation == "invoices.create_draft",
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.status == "COMPLETED",
        )
    )
    # Expiry limits replay, not evidence that a previous commit occurred. If
    # retained, an expired completed record can still safely reconcile a draft.
    if record is not None and isinstance(record.response_body, dict):
        invoice_id: uuid.UUID | None
        try:
            invoice_id = uuid.UUID(str(record.response_body.get("id")))
        except ValueError:
            invoice_id = None
        if invoice_id is not None:
            result = await session.scalar(
                select(SalesDocument.id).where(
                    SalesDocument.id == invoice_id,
                    SalesDocument.tenant_id == context.tenant_id,
                    SalesDocument.document_type == "INVOICE",
                )
            )
            if result is not None:
                return result
    # Missing, unfinished, foreign actor/tenant or malformed evidence all look
    # the same. Never return another operation's payload or existence.
    raise HTTPException(status_code=404, detail="Completed draft request not found")

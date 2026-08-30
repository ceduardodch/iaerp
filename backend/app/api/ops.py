"""Endpoints de observabilidad operativa (``/ops/*``).

Lectura de los fallos terminales que hasta ahora quedaban enterrados en
``dead_letters`` y unicamente se podian ver con SQL manual, mas el reintento
MANUAL (disparado por un humano, scope ``operations:write``) que los
redispara sin esperar al agente de la Fase 3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.platform import OpsFailureRead
from app.services import ops_failures
from app.services.unit_of_work import execute_idempotent

router = APIRouter(tags=["ops"])

Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]


@router.get(
    "/ops/failures",
    response_model=list[OpsFailureRead],
    summary="Listar fallos operativos terminales",
)
async def get_failures(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("operations:read"))],
    status: Annotated[str | None, Query(pattern="^(OPEN|RESOLVED)$")] = None,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OpsFailureRead]:
    return await ops_failures.list_failures(
        session,
        tenant_id=context.tenant_id,
        status=status,
        since=since,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/ops/failures/{failure_id}/retry",
    response_model=OpsFailureRead,
    summary="Reintentar manualmente un fallo operativo terminal",
)
async def post_ops_failure_retry(
    failure_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("operations:write"))],
) -> dict[str, object]:
    async def retry() -> tuple[str, dict[str, object]]:
        read = await ops_failures.retry_failure(session, context, failure_id)
        return str(read.id), read.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="ops.failures.retry",
        idempotency_key=idempotency_key,
        request_payload={"failureId": str(failure_id)},
        action="ops_failure.retried",
        entity_type="dead_letter",
        callback=retry,
    )

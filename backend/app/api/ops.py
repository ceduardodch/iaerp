"""Endpoints de observabilidad operativa (``/ops/*``).

Solo lectura por ahora: expone los fallos terminales que hasta ahora quedaban
enterrados en ``dead_letters`` y unicamente se podian ver con SQL manual.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.platform import OpsFailureRead
from app.services import ops_failures

router = APIRouter(tags=["ops"])

Session = Annotated[AsyncSession, Depends(get_session)]


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

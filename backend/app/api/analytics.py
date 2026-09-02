import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.masters import (
    AnalyticClassificationCreate,
    AnalyticClassificationRead,
    AnalyticClassificationUpdate,
    AnalyticClassificationValueCreate,
    AnalyticClassificationValueRead,
    AnalyticClassificationValueUpdate,
)
from app.services import analytics
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/analytic-classifications", tags=["analytic-classifications"])
Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128)]


@router.get(
    "", response_model=list[AnalyticClassificationRead], summary="Listar clasificaciones analíticas"
)
async def get_analytic_classifications(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:read"))],
    include_inactive: bool = False,
) -> list[AnalyticClassificationRead]:
    return [
        AnalyticClassificationRead.model_validate(item)
        for item in await analytics.list_classifications(
            session, context, include_inactive=include_inactive
        )
    ]


@router.post(
    "",
    response_model=AnalyticClassificationRead,
    status_code=201,
    summary="Crear clasificación analítica",
)
async def post_analytic_classification(
    data: AnalyticClassificationCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        item = await analytics.create_classification(session, context, data)
        return str(item.id), AnalyticClassificationRead.model_validate(item).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="analytics.classifications.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="analytic_classification.created",
        entity_type="analytic_classification",
        callback=create,
    )


@router.put(
    "/{classification_id}",
    response_model=AnalyticClassificationRead,
    summary="Editar o desactivar clasificación analítica",
)
async def put_analytic_classification(
    classification_id: uuid.UUID,
    data: AnalyticClassificationUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        item = await analytics.update_classification(session, context, classification_id, data)
        return str(item.id), AnalyticClassificationRead.model_validate(item).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="analytics.classifications.update",
        idempotency_key=idempotency_key,
        request_payload={"classification_id": str(classification_id), **data.model_dump()},
        action="analytic_classification.updated",
        entity_type="analytic_classification",
        callback=update,
    )


@router.get(
    "/{classification_id}/values",
    response_model=list[AnalyticClassificationValueRead],
    summary="Listar valores de una clasificación",
)
async def get_analytic_classification_values(
    classification_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:read"))],
    include_inactive: bool = False,
) -> list[AnalyticClassificationValueRead]:
    return [
        AnalyticClassificationValueRead.model_validate(item)
        for item in await analytics.list_values(
            session, context, classification_id, include_inactive=include_inactive
        )
    ]


@router.post(
    "/{classification_id}/values",
    response_model=AnalyticClassificationValueRead,
    status_code=201,
    summary="Crear valor controlado",
)
async def post_analytic_classification_value(
    classification_id: uuid.UUID,
    data: AnalyticClassificationValueCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        item = await analytics.create_value(session, context, classification_id, data)
        return str(item.id), AnalyticClassificationValueRead.model_validate(item).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="analytics.values.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="analytic_value.created",
        entity_type="analytic_classification_value",
        callback=create,
    )


@router.put(
    "/{classification_id}/values/{value_id}",
    response_model=AnalyticClassificationValueRead,
    summary="Editar o desactivar valor de clasificación analítica",
)
async def put_analytic_classification_value(
    classification_id: uuid.UUID,
    value_id: uuid.UUID,
    data: AnalyticClassificationValueUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("analytics:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        item = await analytics.update_value(session, context, classification_id, value_id, data)
        return str(item.id), AnalyticClassificationValueRead.model_validate(item).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="analytics.values.update",
        idempotency_key=idempotency_key,
        request_payload={
            "classification_id": str(classification_id),
            "value_id": str(value_id),
            **data.model_dump(),
        },
        action="analytic_value.updated",
        entity_type="analytic_classification_value",
        callback=update,
    )

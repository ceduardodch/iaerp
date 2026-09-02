import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.db.integrity import unique_constraint_name
from app.models.analytics import (
    AnalyticAssignment,
    AnalyticClassification,
    AnalyticClassificationValue,
)
from app.schemas.masters import (
    AnalyticClassificationCreate,
    AnalyticClassificationUpdate,
    AnalyticClassificationValueCreate,
    AnalyticClassificationValueUpdate,
)


async def list_assignments(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
) -> list[dict[str, object]]:
    rows = list(
        await session.scalars(
            select(AnalyticAssignment)
            .where(
                AnalyticAssignment.tenant_id == tenant_id,
                AnalyticAssignment.target_type == target_type,
                AnalyticAssignment.target_id == target_id,
            )
            .order_by(AnalyticAssignment.created_at)
        )
    )
    classifications = {
        item.id: item
        for item in list(
            await session.scalars(
                select(AnalyticClassification).where(
                    AnalyticClassification.tenant_id == tenant_id,
                    AnalyticClassification.id.in_([row.classification_id for row in rows]),
                )
            )
        )
    }
    return [
        {
            "classification_id": row.classification_id,
            "classification_code": classifications[row.classification_id].code,
            "classification_name": classifications[row.classification_id].name,
            "value_id": row.value_id,
            "path": row.path_snapshot,
        }
        for row in rows
        if row.classification_id in classifications
    ]


async def list_assignments_for_targets(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    target_type: str,
    target_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, object]]]:
    """Lee asignaciones de varios documentos sin hacer una consulta por fila."""
    if not target_ids:
        return {}
    rows = list(
        await session.scalars(
            select(AnalyticAssignment)
            .where(
                AnalyticAssignment.tenant_id == tenant_id,
                AnalyticAssignment.target_type == target_type,
                AnalyticAssignment.target_id.in_(target_ids),
            )
            .order_by(AnalyticAssignment.created_at)
        )
    )
    classifications = {
        item.id: item
        for item in list(
            await session.scalars(
                select(AnalyticClassification).where(
                    AnalyticClassification.tenant_id == tenant_id,
                    AnalyticClassification.id.in_([row.classification_id for row in rows]),
                )
            )
        )
    }
    grouped: dict[uuid.UUID, list[dict[str, object]]] = {}
    for row in rows:
        classification = classifications.get(row.classification_id)
        if classification is None:
            continue
        grouped.setdefault(row.target_id, []).append(
            {
                "classification_id": row.classification_id,
                "classification_code": classification.code,
                "classification_name": classification.name,
                "value_id": row.value_id,
                "path": row.path_snapshot,
            }
        )
    return grouped


async def replace_assignments(
    session: AsyncSession,
    context: AuthContext,
    *,
    target_type: str,
    target_id: uuid.UUID,
    value_ids: list[uuid.UUID],
) -> list[dict[str, object]]:
    if len(value_ids) != len(set(value_ids)):
        raise HTTPException(status_code=422, detail="Analytic values must be unique")
    values = list(
        await session.scalars(
            select(AnalyticClassificationValue).where(
                AnalyticClassificationValue.tenant_id == context.tenant_id,
                AnalyticClassificationValue.id.in_(value_ids),
                AnalyticClassificationValue.active.is_(True),
            )
        )
    )
    if len(values) != len(value_ids):
        raise HTTPException(status_code=422, detail="Analytic value not found or inactive")
    if len({item.classification_id for item in values}) != len(values):
        raise HTTPException(
            status_code=422, detail="Only one analytic value per classification is allowed"
        )
    await session.execute(
        delete(AnalyticAssignment).where(
            AnalyticAssignment.tenant_id == context.tenant_id,
            AnalyticAssignment.target_type == target_type,
            AnalyticAssignment.target_id == target_id,
        )
    )
    for value in values:
        session.add(
            AnalyticAssignment(
                tenant_id=context.tenant_id,
                classification_id=value.classification_id,
                value_id=value.id,
                target_type=target_type,
                target_id=target_id,
                path_snapshot=await _path_snapshot(session, context.tenant_id, value),
            )
        )
    await session.flush()
    return await list_assignments(
        session,
        tenant_id=context.tenant_id,
        target_type=target_type,
        target_id=target_id,
    )


async def target_ids_matching_values(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    target_type: str,
    value_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    if not value_ids:
        return set()
    rows = list(
        await session.scalars(
            select(AnalyticAssignment).where(
                AnalyticAssignment.tenant_id == tenant_id,
                AnalyticAssignment.target_type == target_type,
                AnalyticAssignment.value_id.in_(value_ids),
            )
        )
    )
    matching: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in rows:
        matching.setdefault(row.target_id, set()).add(row.value_id)
    required = set(value_ids)
    return {target_id for target_id, matched in matching.items() if matched == required}


async def list_classifications(
    session: AsyncSession, context: AuthContext, *, include_inactive: bool = False
) -> list[AnalyticClassification]:
    filters = [AnalyticClassification.tenant_id == context.tenant_id]
    if not include_inactive:
        filters.append(AnalyticClassification.active.is_(True))
    return list(
        await session.scalars(
            select(AnalyticClassification)
            .where(*filters)
            .order_by(AnalyticClassification.name)
        )
    )


async def create_classification(
    session: AsyncSession, context: AuthContext, data: AnalyticClassificationCreate
) -> AnalyticClassification:
    existing = await session.scalar(
        select(AnalyticClassification).where(
            AnalyticClassification.tenant_id == context.tenant_id,
            AnalyticClassification.code == data.code,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una clasificación con el código {data.code}",
        )
    entity = AnalyticClassification(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError as exc:
        constraint = unique_constraint_name(exc)
        if constraint == "uq_analytic_classifications_tenant_code":
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una clasificación con el código {data.code}",
            ) from exc
        raise
    return entity


async def update_classification(
    session: AsyncSession,
    context: AuthContext,
    classification_id: uuid.UUID,
    data: AnalyticClassificationUpdate,
) -> AnalyticClassification:
    entity = await _get_classification(session, context, classification_id, include_inactive=True)
    if data.name is not None:
        entity.name = data.name
    if data.max_depth is not None:
        entity.max_depth = data.max_depth
    if data.active is not None:
        entity.active = data.active
        if not data.active:
            values = list(
                await session.scalars(
                    select(AnalyticClassificationValue)
                    .where(
                        AnalyticClassificationValue.tenant_id == context.tenant_id,
                        AnalyticClassificationValue.classification_id == classification_id,
                    )
                    .with_for_update()
                )
            )
            for value in values:
                value.active = False
    await session.flush()
    return entity


async def list_values(
    session: AsyncSession,
    context: AuthContext,
    classification_id: uuid.UUID,
    *,
    include_inactive: bool = False,
) -> list[AnalyticClassificationValue]:
    await _get_classification(session, context, classification_id, include_inactive=include_inactive)
    filters = [
        AnalyticClassificationValue.tenant_id == context.tenant_id,
        AnalyticClassificationValue.classification_id == classification_id,
    ]
    if not include_inactive:
        filters.append(AnalyticClassificationValue.active.is_(True))
    return list(
        await session.scalars(
            select(AnalyticClassificationValue)
            .where(*filters)
            .order_by(AnalyticClassificationValue.name)
        )
    )


async def create_value(
    session: AsyncSession,
    context: AuthContext,
    classification_id: uuid.UUID,
    data: AnalyticClassificationValueCreate,
) -> AnalyticClassificationValue:
    classification = await _get_classification(session, context, classification_id)
    existing = await session.scalar(
        select(AnalyticClassificationValue).where(
            AnalyticClassificationValue.tenant_id == context.tenant_id,
            AnalyticClassificationValue.classification_id == classification_id,
            AnalyticClassificationValue.code == data.code,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe el valor {data.code} en {classification.name}",
        )
    if data.parent_id is not None:
        parent = await session.scalar(
            select(AnalyticClassificationValue).where(
                AnalyticClassificationValue.id == data.parent_id,
                AnalyticClassificationValue.tenant_id == context.tenant_id,
                AnalyticClassificationValue.classification_id == classification_id,
                AnalyticClassificationValue.active.is_(True),
            )
        )
        if parent is None:
            raise HTTPException(status_code=422, detail="Parent analytic value not found")
        parent_depth = await _depth(session, context.tenant_id, parent)
        if parent_depth >= classification.max_depth:
            raise HTTPException(
                status_code=422, detail="Analytic classification maximum depth reached"
            )
    entity = AnalyticClassificationValue(
        tenant_id=context.tenant_id,
        classification_id=classification_id,
        **data.model_dump(by_alias=False),
    )
    session.add(entity)
    try:
        await session.flush()
    except IntegrityError as exc:
        constraint = unique_constraint_name(exc)
        if constraint == "uq_analytic_values_tenant_classification_code":
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe el valor {data.code} en {classification.name}",
            ) from exc
        raise
    return entity


async def update_value(
    session: AsyncSession,
    context: AuthContext,
    classification_id: uuid.UUID,
    value_id: uuid.UUID,
    data: AnalyticClassificationValueUpdate,
) -> AnalyticClassificationValue:
    classification = await _get_classification(
        session, context, classification_id, include_inactive=True
    )
    entity = await session.scalar(
        select(AnalyticClassificationValue)
        .where(
            AnalyticClassificationValue.id == value_id,
            AnalyticClassificationValue.tenant_id == context.tenant_id,
            AnalyticClassificationValue.classification_id == classification_id,
        )
        .with_for_update()
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Analytic classification value not found")
    if data.name is not None:
        entity.name = data.name
    if "color" in data.model_fields_set:
        entity.color = data.color
    if data.active is not None:
        if data.active and not classification.active:
            raise HTTPException(
                status_code=409,
                detail="No se puede activar un valor de una clasificación inactiva",
            )
        if data.active and entity.parent_id is not None:
            parent = await session.scalar(
                select(AnalyticClassificationValue).where(
                    AnalyticClassificationValue.id == entity.parent_id,
                    AnalyticClassificationValue.tenant_id == context.tenant_id,
                    AnalyticClassificationValue.active.is_(True),
                )
            )
            if parent is None:
                raise HTTPException(
                    status_code=409,
                    detail="No se puede activar un subnivel cuyo padre está inactivo",
                )
        entity.active = data.active
        if not data.active:
            descendants = list(
                await session.scalars(
                    select(AnalyticClassificationValue)
                    .where(
                        AnalyticClassificationValue.tenant_id == context.tenant_id,
                        AnalyticClassificationValue.classification_id == classification_id,
                    )
                    .with_for_update()
                )
            )
            inactive_ids = {entity.id}
            changed = True
            while changed:
                changed = False
                for candidate in descendants:
                    if candidate.parent_id in inactive_ids and candidate.id not in inactive_ids:
                        inactive_ids.add(candidate.id)
                        changed = True
            for candidate in descendants:
                if candidate.id in inactive_ids:
                    candidate.active = False
    await session.flush()
    return entity


async def _get_classification(
    session: AsyncSession,
    context: AuthContext,
    classification_id: uuid.UUID,
    *,
    include_inactive: bool = False,
) -> AnalyticClassification:
    filters = [
        AnalyticClassification.id == classification_id,
        AnalyticClassification.tenant_id == context.tenant_id,
    ]
    if not include_inactive:
        filters.append(AnalyticClassification.active.is_(True))
    entity = await session.scalar(
        select(AnalyticClassification).where(*filters)
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="Analytic classification not found")
    return entity


async def _depth(
    session: AsyncSession, tenant_id: uuid.UUID, value: AnalyticClassificationValue
) -> int:
    depth = 1
    parent_id = value.parent_id
    while parent_id is not None:
        parent = await session.scalar(
            select(AnalyticClassificationValue).where(
                AnalyticClassificationValue.id == parent_id,
                AnalyticClassificationValue.tenant_id == tenant_id,
            )
        )
        if parent is None:
            raise HTTPException(status_code=422, detail="Invalid analytic value hierarchy")
        depth += 1
        parent_id = parent.parent_id
    return depth


async def _path_snapshot(
    session: AsyncSession, tenant_id: uuid.UUID, value: AnalyticClassificationValue
) -> list[dict[str, str]]:
    path = [{"code": value.code, "name": value.name}]
    parent_id = value.parent_id
    while parent_id is not None:
        parent = await session.scalar(
            select(AnalyticClassificationValue).where(
                AnalyticClassificationValue.id == parent_id,
                AnalyticClassificationValue.tenant_id == tenant_id,
            )
        )
        if parent is None:
            raise HTTPException(status_code=422, detail="Invalid analytic value hierarchy")
        path.append({"code": parent.code, "name": parent.name})
        parent_id = parent.parent_id
    return list(reversed(path))

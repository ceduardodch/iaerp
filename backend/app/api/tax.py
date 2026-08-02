"""API del modulo tributario Ecuador (ADR 0012).

Etapa E1: periodos y carga de evidencia. La lectura del contenido (crear
``FiscalDocument`` desde el XML/TXT) llega en la etapa E2.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.tax import TaxEvidenceRead, TaxPeriodCreate, TaxPeriodRead
from app.services.tax import evidence as evidence_service
from app.services.tax import periods as periods_service
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/tax", tags=["tax"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/periods", response_model=list[TaxPeriodRead])
async def get_periods(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    obligation_type: Annotated[str | None, Query(pattern="^(IVA|ATS|RDEP|RENTA|ADI)$")] = None,
) -> list[TaxPeriodRead]:
    records = await periods_service.list_periods(
        session,
        context,
        year=year,
        obligation_type=obligation_type,
    )
    return [TaxPeriodRead.model_validate(record) for record in records]


@router.post("/periods", response_model=TaxPeriodRead, status_code=201)
async def post_period(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    data: TaxPeriodCreate,
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        period = await periods_service.get_or_create_period(
            session,
            context,
            year=data.year,
            month=data.month,
            obligation_type=data.obligation_type,
            due_date=data.due_date,
            notes=data.notes,
        )
        payload = TaxPeriodRead.model_validate(period).model_dump(mode="json", by_alias=True)
        return str(period.id), payload

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.period.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="tax.period.created",
        entity_type="tax_period",
        callback=create,
    )


@router.get("/evidence", response_model=list[TaxEvidenceRead])
async def get_evidence(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    tax_period_id: uuid.UUID | None = None,
) -> list[TaxEvidenceRead]:
    records = await evidence_service.list_evidence(
        session,
        context,
        tax_period_id=tax_period_id,
    )
    return [TaxEvidenceRead.model_validate(record) for record in records]


@router.post("/evidence", response_model=TaxEvidenceRead, status_code=201)
async def post_evidence(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    file: Annotated[UploadFile, File()],
    origin: Annotated[str, Form(max_length=30)] = "MANUAL",
    # El resto de la API usa camelCase (APIModel), asi que el campo del
    # formulario tambien: sin el alias, FastAPI buscaria `tax_period_id` y la
    # evidencia quedaria sin periodo silenciosamente.
    tax_period_id: Annotated[uuid.UUID | None, Form(alias="taxPeriodId")] = None,
) -> dict[str, object]:
    """Guarda un archivo del SRI como evidencia.

    El archivo se identifica por su hash: subirlo dos veces devuelve el mismo
    registro con ``duplicate=true`` y no altera el periodo.
    """
    payload = await file.read(evidence_service.MAX_EVIDENCE_SIZE + 1)

    async def upload() -> tuple[str, dict[str, object]]:
        record, duplicate = await evidence_service.upload_evidence(
            session,
            context,
            filename=file.filename,
            data=payload,
            origin=origin,
            tax_period_id=tax_period_id,
        )
        response = TaxEvidenceRead.model_validate(record)
        response.duplicate = duplicate
        return str(record.id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.evidence.upload",
        idempotency_key=idempotency_key,
        request_payload={
            "filename": file.filename,
            "size": len(payload),
        },
        action="tax.evidence.uploaded",
        entity_type="tax_evidence",
        callback=upload,
    )


@router.get("/evidence/{evidence_id}/download")
async def get_evidence_download(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    evidence_id: uuid.UUID,
) -> dict[str, str]:
    url = await evidence_service.download_url(session, context, evidence_id=evidence_id)
    return {"url": url}

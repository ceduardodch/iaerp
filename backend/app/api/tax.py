"""API del modulo tributario Ecuador (ADR 0012).

Etapa E1: periodos y carga de evidencia. La lectura del contenido (crear
``FiscalDocument`` desde el XML/TXT) llega en la etapa E2.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.core.timezones import today_in_fiscal_timezone
from app.db.session import get_session
from app.models.payables import Payable
from app.models.platform import Tenant
from app.models.tax import FiscalDocument, SRIValidationIssue, TaxAnnex
from app.schemas.tax import (
    BulkItemRead,
    BulkResultRead,
    CurrentMonthTaxRead,
    DashboardTaxRead,
    DocumentDossierRead,
    DossierMovementRead,
    DossierRetentionRead,
    FiscalDocumentRead,
    HistoricalTaxCandidateRead,
    HistoricalTaxExceptionApprove,
    IngestResultRead,
    IvaSummaryRead,
    MonthlySalesTrendRead,
    OwnDocumentsResultRead,
    PurchaseDocumentRead,
    PurchaseTaxLineRead,
    SRIValidationIssueCreate,
    SRIValidationIssueRead,
    TaxAnnexRead,
    TaxEvidenceRead,
    TaxFormFieldRead,
    TaxPeriodCreate,
    TaxPeriodRead,
    TaxPeriodStatusUpdate,
)
from app.services import analytics, receivables
from app.services.tax import annexes as annexes_service
from app.services.tax import bulk as bulk_service
from app.services.tax import dossier as dossier_service
from app.services.tax import evidence as evidence_service
from app.services.tax import form_fields, historical_exception, own_documents
from app.services.tax import ingest as ingest_service
from app.services.tax import iva as iva_service
from app.services.tax import periods as periods_service
from app.services.tax import reporting as reporting_service
from app.services.tax.formatting import format_amount
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/tax", tags=["tax"])

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/dashboard",
    response_model=DashboardTaxRead,
    summary="Ver evolución mensual y corte documental de IVA",
)
async def get_tax_dashboard(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    months: Annotated[int, Query(ge=6, le=24)] = 12,
    as_of: Annotated[date | None, Query()] = None,
) -> DashboardTaxRead:
    """Evolución de ventas y corte documental de IVA del mes."""
    report = await reporting_service.dashboard_tax_report(
        session,
        context,
        as_of=as_of or today_in_fiscal_timezone(),
        months=months,
    )
    current = report.current_month
    return DashboardTaxRead(
        trend=[
            MonthlySalesTrendRead(
                year=point.year,
                month=point.month,
                total=format_amount(point.total),
                invoice_count=point.invoice_count,
                credit_note_count=point.credit_note_count,
            )
            for point in report.trend
        ],
        current_month=CurrentMonthTaxRead(
            year=current.year,
            month=current.month,
            authorized_sales_total=format_amount(current.authorized_sales_total),
            authorized_sales_count=current.authorized_sales_count,
            evidenced_sales_total=format_amount(current.evidenced_sales_total),
            evidenced_sales_count=current.evidenced_sales_count,
            purchases_total=format_amount(current.purchases_total),
            purchase_count=current.purchase_count,
            iva_generated=format_amount(current.iva_generated),
            iva_credit=format_amount(current.iva_credit),
            retained_iva=format_amount(current.retained_iva),
            iva_payable=format_amount(current.iva_payable),
            iva_credit_balance=format_amount(current.iva_credit_balance),
            is_preliminary=current.is_preliminary,
            preliminary_reasons=current.preliminary_reasons,
            needs_accounting_review=current.needs_accounting_review,
        ),
    )


@router.get(
    "/purchases",
    response_model=list[PurchaseDocumentRead],
    summary="Listar compras recibidas desde evidencia tributaria",
)
async def get_purchases(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> list[PurchaseDocumentRead]:
    """Compras recibidas desde evidencia real, agrupables por fecha del XML."""
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="Year is required when filtering by month")
    records = await reporting_service.list_purchases(
        session,
        context,
        year=year,
        month=month,
    )
    return [
        PurchaseDocumentRead(
            id=record.id,
            doc_type=record.doc_type,
            access_key=record.access_key,
            issue_date=record.issue_date,
            document_number=record.document_number,
            supplier_identification=record.supplier_identification,
            supplier_name=record.supplier_name,
            subtotal=format_amount(record.subtotal),
            tax_total=format_amount(record.tax_total),
            total=format_amount(record.total),
            payment_methods=record.payment_methods,
            is_preliminary=record.is_preliminary,
            taxes=[
                PurchaseTaxLineRead(
                    sri_tax_code=tax.sri_tax_code,
                    tax_bracket=tax.tax_bracket,
                    rate=format_amount(tax.rate),
                    base_amount=format_amount(tax.base_amount),
                    tax_amount=format_amount(tax.tax_amount),
                )
                for tax in record.taxes
            ],
        )
        for record in records
    ]


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


@router.post("/periods/{period_id}/status", response_model=TaxPeriodRead)
async def post_period_status(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    period_id: uuid.UUID,
    data: TaxPeriodStatusUpdate,
) -> dict[str, object]:
    """Confirma manualmente que un periodo está listo o ya fue declarado."""

    async def update() -> tuple[str, dict[str, object]]:
        period = await periods_service.set_manual_status(
            session,
            context,
            period_id=period_id,
            target_status=data.target_status,
            confirmed=data.confirmed,
        )
        return (
            str(period.id),
            TaxPeriodRead.model_validate(period).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.period.status.update",
        idempotency_key=idempotency_key,
        request_payload={"periodId": str(period_id), **data.model_dump(mode="json")},
        action="tax.period.status.updated",
        entity_type="tax_period",
        callback=update,
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


async def _tenant_ruc(session: AsyncSession, context: AuthContext) -> str:
    """RUC de la entidad: distingue comprobantes emitidos de recibidos."""
    ruc = await session.scalar(select(Tenant.ruc).where(Tenant.id == context.tenant_id))
    if not ruc:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return str(ruc)


@router.post("/evidence/{evidence_id}/ingest", response_model=IngestResultRead)
async def post_evidence_ingest(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    evidence_id: uuid.UUID,
) -> dict[str, object]:
    """Lee un archivo ya cargado y persiste los comprobantes que contiene."""
    ruc = await _tenant_ruc(session, context)

    async def run() -> tuple[str, dict[str, object]]:
        result = await ingest_service.ingest_evidence(
            session,
            context,
            evidence_id=evidence_id,
            tenant_ruc=ruc,
        )
        payload = IngestResultRead(
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            preliminary=result.preliminary,
            notes=result.notes,
        )
        return str(evidence_id), payload.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.evidence.ingest",
        idempotency_key=idempotency_key,
        request_payload={"evidenceId": str(evidence_id)},
        action="tax.evidence.ingested",
        entity_type="tax_evidence",
        callback=run,
    )


def _bulk_payload(
    result: bulk_service.BulkResult, *, retentions_applied: int = 0
) -> dict[str, object]:
    return BulkResultRead(
        items=[BulkItemRead.model_validate(item) for item in result.items],
        created=result.created,
        updated=result.updated,
        duplicates=result.duplicates,
        errors=result.errors,
        periods=result.periods,
        notes=result.notes,
        retention_count=result.retention_count,
        retentions_applied=retentions_applied,
    ).model_dump(mode="json", by_alias=True)


@router.post("/evidence/bulk", response_model=BulkResultRead)
async def post_evidence_bulk(
    files: Annotated[list[UploadFile], File()],
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    apply: Annotated[bool, Form()] = False,
    apply_retentions: Annotated[bool, Form(alias="applyRetentions")] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    """Carga en bloque los comprobantes de un periodo.

    Con ``apply=false`` solo clasifica y **no escribe nada**: es el previo que el
    usuario revisa. Con ``apply=true`` guarda la evidencia y registra los
    comprobantes. Las retenciones se aplican a cartera solo si ademas se pide
    ``applyRetentions``, respetando la regla de que un cobro necesita respaldo.
    """
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")
    if len(files) > bulk_service.MAX_BULK_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"A maximum of {bulk_service.MAX_BULK_FILES} files is allowed",
        )

    ruc = await _tenant_ruc(session, context)
    payload_files = [
        (
            file.filename or "comprobante.xml",
            await file.read(evidence_service.MAX_EVIDENCE_SIZE + 1),
        )
        for file in files
    ]

    if not apply:
        preview = await bulk_service.preview_bulk(
            session,
            context,
            files=payload_files,
            tenant_ruc=ruc,
        )
        return _bulk_payload(preview)

    if idempotency_key is None or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key header is required to apply a bulk upload",
        )

    async def register() -> tuple[str, dict[str, object]]:
        result = await bulk_service.apply_bulk(
            session,
            context,
            files=payload_files,
            tenant_ruc=ruc,
        )
        applied = 0
        if apply_retentions:
            # Se delega en el flujo de cartera, que ya cruza la retencion con su
            # factura y registra el movimiento; aqui no se reimplementa.
            candidates = bulk_service.retention_files(payload_files)
            if candidates:
                batch = await receivables.import_retention_xml_batch(
                    session,
                    context=context,
                    files=candidates,
                    apply=True,
                    correlation_id=str(uuid.uuid4()),
                    idempotency_key=f"{idempotency_key}-retentions",
                )
                applied = sum(1 for item in batch.items if item.status == "MATCHED")
        return str(context.tenant_id), _bulk_payload(result, retentions_applied=applied)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.evidence.bulk",
        idempotency_key=idempotency_key,
        request_payload={
            "files": [name for name, _content in payload_files],
            "applyRetentions": apply_retentions,
        },
        action="tax.evidence.bulk_uploaded",
        entity_type="tax_evidence",
        callback=register,
    )


@router.post("/periods/{period_id}/import-issued", response_model=OwnDocumentsResultRead)
async def post_period_import_issued(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    period_id: uuid.UUID,
) -> dict[str, object]:
    """Trae al periodo las facturas AUTORIZADAS que la propia entidad emitio.

    Evita tener que descargar y subir los comprobantes propios: se leen del XML
    firmado que IAERP ya guardo al emitirlos.
    """
    ruc = await _tenant_ruc(session, context)

    async def run() -> tuple[str, dict[str, object]]:
        period = await periods_service.get_period(session, context, period_id=period_id)
        result = await own_documents.import_issued_documents(
            session,
            context,
            period=period,
            tenant_ruc=ruc,
        )
        # Importar ventas puede cambiar el estado del periodo (p.ej. de
        # PENDIENTE_DESCARGA a LISTO_REVISAR).
        await periods_service.refresh_period_statuses(session, context)
        payload = OwnDocumentsResultRead(
            created=result.created,
            updated=result.updated,
            skipped=result.skipped,
            notes=result.notes,
        )
        return str(period_id), payload.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.period.import_issued",
        idempotency_key=idempotency_key,
        request_payload={"periodId": str(period_id)},
        action="tax.period.issued_imported",
        entity_type="tax_period",
        callback=run,
    )


@router.get(
    "/periods/{period_id}/historical-tax-candidates",
    response_model=list[HistoricalTaxCandidateRead],
)
async def get_historical_tax_candidates(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    period_id: uuid.UUID,
) -> list[HistoricalTaxCandidateRead]:
    """RIDE autorizados que pueden aprobarse como excepción IVA/ATS."""
    period = await periods_service.get_period(session, context, period_id=period_id)
    candidates = await historical_exception.list_candidates(
        session, context, period=period
    )
    return [HistoricalTaxCandidateRead.model_validate(candidate) for candidate in candidates]


@router.post(
    "/periods/{period_id}/historical-tax-candidates/{sales_document_id}/approve",
    response_model=FiscalDocumentRead,
)
async def post_historical_tax_candidate_approve(
    payload: HistoricalTaxExceptionApprove,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    period_id: uuid.UUID,
    sales_document_id: uuid.UUID,
) -> dict[str, object]:
    """Aprueba una excepción ATS; no crea un XML SRI ni toca Cartera."""

    async def approve() -> tuple[str, dict[str, object]]:
        period = await periods_service.get_period(session, context, period_id=period_id)
        fiscal = await historical_exception.approve_candidate(
            session,
            context,
            period=period,
            sales_document_id=sales_document_id,
            confirmed=payload.confirmed,
            evidence_reference=payload.evidence_reference,
        )
        await periods_service.refresh_period_statuses(session, context)
        response = FiscalDocumentRead.model_validate(fiscal)
        return str(fiscal.id), response.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.historical_exception.approve",
        idempotency_key=idempotency_key,
        request_payload={
            "periodId": str(period_id),
            "salesDocumentId": str(sales_document_id),
            "confirmed": payload.confirmed,
            "evidenceReference": payload.evidence_reference,
        },
        action="tax.historical_exception.approved",
        entity_type="fiscal_document",
        callback=approve,
    )


@router.get("/periods/{period_id}/documents", response_model=list[FiscalDocumentRead])
async def get_period_documents(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    period_id: uuid.UUID,
) -> list[FiscalDocumentRead]:
    period = await periods_service.get_period(session, context, period_id=period_id)
    documents = list(await session.scalars(
        select(FiscalDocument)
        .where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.tax_period_id == period.id,
        )
        .order_by(FiscalDocument.issue_date, FiscalDocument.access_key)
    ))
    payables = list(await session.scalars(
        select(Payable).where(
            Payable.tenant_id == context.tenant_id,
            Payable.fiscal_document_id.in_([document.id for document in documents]),
        )
    )) if documents else []
    payable_by_document_id = {
        payable.fiscal_document_id: payable.id
        for payable in payables
        if payable.fiscal_document_id is not None
    }
    assignments_by_payable = await analytics.list_assignments_for_targets(
        session,
        tenant_id=context.tenant_id,
        target_type="payable",
        target_ids=[payable.id for payable in payables],
    )
    assignments_by_document_id = {
        document_id: assignments_by_payable.get(payable_id, [])
        for document_id, payable_id in payable_by_document_id.items()
    }
    return [
        FiscalDocumentRead.model_validate(document).model_copy(
            update={
                "analytic_assignments": assignments_by_document_id.get(document.id, [])
            }
        )
        for document in documents
    ]


@router.get("/documents/{document_id}/dossier", response_model=DocumentDossierRead)
async def get_document_dossier(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    document_id: uuid.UUID,
) -> DocumentDossierRead:
    """Historia del comprobante: retenciones, cobros con su referencia y saldo."""
    record = await dossier_service.build_dossier(session, context, document_id=document_id)
    return DocumentDossierRead(
        document_id=record.document_id,
        doc_type=record.doc_type,
        direction=record.direction,
        access_key=record.access_key,
        issue_date=record.issue_date,
        counterparty_name=record.counterparty_name,
        total=record.total,
        payment_methods=record.payment_methods,
        retentions=[
            DossierRetentionRead(
                access_key=item.access_key,
                issue_date=item.issue_date,
                issuer_name=item.issuer_name,
                iva_amount=item.iva_amount,
                income_tax_amount=item.income_tax_amount,
            )
            for item in record.retentions
        ],
        movements=[
            DossierMovementRead(
                movement_type=item.movement_type,
                amount=item.amount,
                occurred_at=item.occurred_at,
                reference=item.reference,
                bank_reference=item.bank_reference,
            )
            for item in record.movements
        ],
        receivable_id=record.receivable_id,
        receivable_status=record.receivable_status,
        retained_iva=record.retained_iva,
        retained_income_tax=record.retained_income_tax,
        collected_amount=record.collected_amount,
        outstanding_amount=record.outstanding_amount,
        expected_net=record.expected_net,
        net_difference=record.net_difference,
        notes=record.notes,
    )


@router.get("/periods/{period_id}/iva", response_model=IvaSummaryRead)
async def get_period_iva(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    period_id: uuid.UUID,
) -> IvaSummaryRead:
    """Cifras del periodo y campos del formulario listos para copiar."""
    period = await periods_service.get_period(session, context, period_id=period_id)
    summary = await iva_service.compute_iva(session, context, period=period)

    records = await form_fields.ensure_form_field_map(session, context)
    reference = form_fields.period_reference_date(period.year, period.month)
    pending_review = form_fields.review_pending_codes()

    fields = [
        TaxFormFieldRead(
            field_code=record.field_code,
            label=record.label,
            # Mismo formato que las claves de `amounts`, para poder cruzarlos.
            source_key=to_camel(record.source_key),
            is_paste=record.is_paste,
            value=summary.amounts[record.source_key].formatted
            if record.source_key in summary.amounts
            else "0.00",
            document_count=len(summary.amounts[record.source_key].document_ids)
            if record.source_key in summary.amounts
            else 0,
            needs_review=record.field_code in pending_review,
        )
        for record in form_fields.fields_for_date(records, reference)
    ]

    return IvaSummaryRead(
        period_id=period.id,
        year=period.year,
        month=period.month,
        status=period.status,
        document_count=summary.document_count,
        is_preliminary=summary.is_preliminary,
        preliminary_reasons=summary.preliminary_reasons,
        pending_purchase_count=summary.pending_purchase_count,
        pending_purchase_subtotal=format_amount(summary.pending_purchase_subtotal),
        pending_purchase_tax_total=format_amount(summary.pending_purchase_tax_total),
        pending_purchase_total=format_amount(summary.pending_purchase_total),
        # Las claves del motor son snake_case; se exponen en camelCase para
        # mantener una sola convencion en toda la API.
        amounts={to_camel(key): value for key, value in summary.as_dict().items()},
        fields=fields,
    )


@router.post("/periods/{period_id}/ats", response_model=TaxAnnexRead, status_code=201)
async def post_period_ats(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    period_id: uuid.UUID,
) -> dict[str, object]:
    """Genera un ZIP ATS privado; no lo entrega ni lo envia al SRI."""

    async def generate() -> tuple[str, dict[str, object]]:
        period = await periods_service.get_period(session, context, period_id=period_id)
        annex = await annexes_service.generate_ats(session, context, period=period)
        url = await annexes_service.download_url(session, context, annex_id=annex.id)
        payload = TaxAnnexRead.model_validate(annex)
        payload.download_url = url
        return str(annex.id), payload.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.annex.ats.generate",
        idempotency_key=idempotency_key,
        request_payload={"periodId": str(period_id), "annexType": "ATS"},
        action="tax.annex.ats.generated",
        entity_type="tax_annex",
        callback=generate,
    )


@router.get("/annexes/{annex_id}/download")
async def get_annex_download(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    annex_id: uuid.UUID,
) -> dict[str, str]:
    """Devuelve una URL privada y temporal del ZIP; no entrega el anexo al SRI."""
    return {"url": await annexes_service.download_url(session, context, annex_id=annex_id)}


@router.get("/annexes/{annex_id}/issues", response_model=list[SRIValidationIssueRead])
async def get_annex_issues(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:read"))],
    annex_id: uuid.UUID,
) -> list[SRIValidationIssueRead]:
    annex = await session.scalar(
        select(TaxAnnex).where(TaxAnnex.tenant_id == context.tenant_id, TaxAnnex.id == annex_id)
    )
    if annex is None:
        raise HTTPException(status_code=404, detail="Tax annex not found")
    records = await session.scalars(
        select(SRIValidationIssue)
        .where(
            SRIValidationIssue.tenant_id == context.tenant_id,
            SRIValidationIssue.tax_annex_id == annex.id,
        )
        .order_by(SRIValidationIssue.created_at.desc())
    )
    return [SRIValidationIssueRead.model_validate(record) for record in records]


@router.post("/annexes/{annex_id}/issues", response_model=SRIValidationIssueRead, status_code=201)
async def post_annex_issue(
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("tax:write"))],
    annex_id: uuid.UUID,
    data: SRIValidationIssueCreate,
) -> dict[str, object]:
    """Registra un error devuelto por el SRI; nunca lo corrige ni lo envia."""

    async def create() -> tuple[str, dict[str, object]]:
        annex = await session.scalar(
            select(TaxAnnex).where(
                TaxAnnex.tenant_id == context.tenant_id, TaxAnnex.id == annex_id
            )
        )
        if annex is None:
            raise HTTPException(status_code=404, detail="Tax annex not found")
        issue = SRIValidationIssue(
            tenant_id=context.tenant_id,
            tax_annex_id=annex.id,
            severity=data.severity,
            line_number=data.line_number,
            column_number=data.column_number,
            message=data.message,
            suggested_fix=data.suggested_fix,
        )
        session.add(issue)
        await session.flush()
        return (
            str(issue.id),
            SRIValidationIssueRead.model_validate(issue).model_dump(mode="json", by_alias=True),
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="tax.annex.issue.create",
        idempotency_key=idempotency_key,
        request_payload={"annexId": str(annex_id), **data.model_dump(mode="json")},
        action="tax.annex.issue.created",
        entity_type="sri_validation_issue",
        callback=create,
    )

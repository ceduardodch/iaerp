from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.schemas.bank_reconciliation import BankStatementImportRead
from app.schemas.masters import AnalyticAssignmentsUpdate
from app.schemas.payables import (
    BankDebitAllocationInput,
    ExpenseRuleCreate,
    ExpenseRuleRead,
    PayableAdjustmentCreate,
    PayableClassificationUpdate,
    PayableCreate,
    PayableDocumentBulkReviewCreate,
    PayableDocumentBulkReviewItemRead,
    PayableDocumentBulkReviewRead,
    PayableDocumentReviewCreate,
    PayableFromDocumentCreate,
    PayableMovementRead,
    PayablePaymentCreate,
    PayableRead,
    PayableReversalCreate,
    PaymentScheduleCreate,
    PaymentScheduleRead,
)
from app.services import bank_reconciliation, payables
from app.services.unit_of_work import execute_idempotent

router = APIRouter(tags=["payables"])

Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]


@router.get(
    "/payables",
    response_model=list[PayableRead],
    summary="Listar cuentas por pagar",
)
async def get_payables(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:read"))],
    status: Annotated[str | None, Query(pattern="^(OPEN|PARTIAL|SETTLED|VOIDED)$")] = None,
    due_before: Annotated[date | None, Query(alias="dueBefore")] = None,
    analytic_value_id: Annotated[list[uuid.UUID] | None, Query(alias="analyticValueId")] = None,
    party_id: Annotated[uuid.UUID | None, Query(alias="partyId")] = None,
) -> list[PayableRead]:
    return await payables.list_payables(
        session,
        tenant_id=context.tenant_id,
        status=status,
        due_before=due_before,
        analytic_value_ids=analytic_value_id,
        supplier_id=party_id,
    )


@router.get(
    "/payables/{payable_id}",
    response_model=PayableRead,
    summary="Consultar una cuenta por pagar",
)
async def get_payable(
    payable_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:read"))],
) -> PayableRead:
    return await payables.get_payable(session, tenant_id=context.tenant_id, payable_id=payable_id)


@router.put(
    "/payables/{payable_id}/analytic-assignments",
    response_model=PayableRead,
    summary="Actualizar clasificaciones analíticas de una CxP",
)
async def put_payable_analytic_assignments(
    payable_id: uuid.UUID,
    data: AnalyticAssignmentsUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        item = await payables.update_payable_analytic_assignments(
            session, context, payable_id, value_ids=data.value_ids
        )
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.analytic_assignments.update",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payable.analytic_assignments_updated",
        entity_type="payable",
        callback=update,
    )


@router.put(
    "/payables/{payable_id}/classification",
    response_model=PayableRead,
    summary="Corregir el uso fiscal y las clasificaciones de una CxP",
)
async def put_payable_classification(
    payable_id: uuid.UUID,
    data: PayableClassificationUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        item = await payables.update_payable_classification(
            session,
            context,
            payable_id=payable_id,
            data=data,
        )
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.classification.update",
        idempotency_key=idempotency_key,
        request_payload={"payable_id": str(payable_id), **data.model_dump(mode="json")},
        action="payable.classification_updated",
        entity_type="payable",
        callback=update,
        audit_details={
            "reason": data.reason,
            "tax_classification": data.tax_classification,
            "internal_classification": data.internal_classification,
        },
    )


@router.post(
    "/payables",
    response_model=PayableRead,
    status_code=201,
    summary="Crear una compra o cuenta por pagar",
)
async def post_payable(
    data: PayableCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        item = await payables.create_payable(session, context, data)
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payable.created",
        entity_type="payable",
        callback=create,
    )


@router.post(
    "/payables/from-document",
    response_model=PayableRead,
    status_code=201,
    summary="Crear o enlazar CxP desde un documento fiscal",
)
async def post_payable_from_document(
    data: PayableFromDocumentCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:extract"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        item = await payables.create_from_fiscal_document(
            session, context, document_id=data.document_id
        )
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.create_from_document",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payable.document_linked",
        entity_type="payable",
        callback=create,
    )


@router.post(
    "/payables/from-document/review",
    response_model=PayableRead,
    status_code=201,
    summary="Enlazar y revisar una compra cargada desde el SRI",
)
async def post_payable_document_review(
    data: PayableDocumentReviewCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[
        AuthContext,
        Depends(require_scopes("payables:extract", "payables:write")),
    ],
) -> dict[str, object]:
    async def review() -> tuple[str, dict[str, object]]:
        item = await payables.review_fiscal_document(session, context, data)
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.review_from_document",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="payable.document_reviewed",
        entity_type="payable",
        callback=review,
    )


@router.post(
    "/payables/from-document/reviews",
    response_model=PayableDocumentBulkReviewRead,
    summary="Revisar varias compras cargadas desde el SRI",
)
async def post_payable_document_bulk_review(
    data: PayableDocumentBulkReviewCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[
        AuthContext,
        Depends(require_scopes("payables:extract", "payables:write")),
    ],
) -> PayableDocumentBulkReviewRead:
    results: list[PayableDocumentBulkReviewItemRead] = []
    base_payload = data.model_dump(mode="json")

    for document_id in data.document_ids:
        child_key = (
            "sri-bulk:" + hashlib.sha256(f"{idempotency_key}:{document_id}".encode()).hexdigest()
        )
        item_payload = {**base_payload, "documentIds": [str(document_id)]}

        async def review_item(
            current_document_id: uuid.UUID = document_id,
        ) -> tuple[str, dict[str, object]]:
            review_data, protected, already_reviewed = await payables.prepare_bulk_fiscal_review(
                session,
                context,
                document_id=current_document_id,
                data=data,
            )
            item = await payables.review_fiscal_document(
                session,
                context,
                review_data,
                allow_existing_classification=already_reviewed,
            )
            status = "SKIPPED" if already_reviewed else "PROTECTED" if protected else "REVIEWED"
            return str(item.id), {
                "documentId": str(current_document_id),
                "payableId": str(item.id),
                "status": status,
                "detail": (
                    "La clasificación existente se conservó y el XML quedó enlazado"
                    if already_reviewed
                    else "Pago y tags existentes conservados"
                    if protected
                    else "Compra revisada"
                ),
            }

        try:
            response = await execute_idempotent(
                session,
                context=context,
                operation="payables.review_from_document.bulk_item",
                idempotency_key=child_key,
                request_payload=item_payload,
                action="payable.document_reviewed",
                entity_type="payable",
                callback=review_item,
            )
            results.append(PayableDocumentBulkReviewItemRead.model_validate(response))
        except HTTPException as exc:
            detail = str(exc.detail)
            skipped = exc.status_code == 409 and detail == "This SRI purchase was already reviewed"
            results.append(
                PayableDocumentBulkReviewItemRead(
                    document_id=document_id,
                    status="SKIPPED" if skipped else "FAILED",
                    detail=("La compra ya había sido revisada" if skipped else detail),
                )
            )

    return PayableDocumentBulkReviewRead(
        reviewed_count=sum(item.status == "REVIEWED" for item in results),
        protected_count=sum(item.status == "PROTECTED" for item in results),
        skipped_count=sum(item.status == "SKIPPED" for item in results),
        failed_count=sum(item.status == "FAILED" for item in results),
        items=results,
    )


@router.post(
    "/payables/{payable_id}/payments",
    response_model=PayableRead,
    status_code=201,
    summary="Registrar un pago a proveedor",
)
async def post_payable_payment(
    payable_id: uuid.UUID,
    data: PayablePaymentCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def record() -> tuple[str, dict[str, object]]:
        item = await payables.record_payment(session, context, payable_id=payable_id, data=data)
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.record_payment",
        idempotency_key=idempotency_key,
        request_payload={"payable_id": str(payable_id), **data.model_dump(mode="json")},
        action="supplier_payment.recorded",
        entity_type="payable",
        callback=record,
    )


@router.post(
    "/payables/{payable_id}/adjustments",
    response_model=PayableRead,
    status_code=201,
    summary="Registrar retención o nota de crédito",
)
async def post_payable_adjustment(
    payable_id: uuid.UUID,
    data: PayableAdjustmentCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def record() -> tuple[str, dict[str, object]]:
        item = await payables.record_adjustment(session, context, payable_id=payable_id, data=data)
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.record_adjustment",
        idempotency_key=idempotency_key,
        request_payload={"payable_id": str(payable_id), **data.model_dump(mode="json")},
        action="payable.adjustment_recorded",
        entity_type="payable",
        callback=record,
    )


@router.get(
    "/payables/{payable_id}/movements",
    response_model=list[PayableMovementRead],
    summary="Listar movimientos de una cuenta por pagar",
)
async def get_payable_movements(
    payable_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:read"))],
) -> list[PayableMovementRead]:
    items = await payables.list_movements(
        session, tenant_id=context.tenant_id, payable_id=payable_id
    )
    return [PayableMovementRead.model_validate(item) for item in items]


@router.post(
    "/payables/{payable_id}/movements/{movement_id}/reversal",
    response_model=PayableRead,
    status_code=201,
    summary="Revertir un movimiento de CxP",
)
async def post_payable_reversal(
    payable_id: uuid.UUID,
    movement_id: uuid.UUID,
    data: PayableReversalCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def reverse() -> tuple[str, dict[str, object]]:
        item = await payables.reverse_movement(
            session,
            context,
            payable_id=payable_id,
            movement_id=movement_id,
            reason=data.reason,
            effective_date=data.effective_date,
        )
        return str(item.id), item.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.reverse_movement",
        idempotency_key=idempotency_key,
        request_payload={
            "payable_id": str(payable_id),
            "movement_id": str(movement_id),
            **data.model_dump(mode="json"),
        },
        action="payable.movement_reversed",
        entity_type="payable",
        callback=reverse,
    )


@router.post(
    "/payables/{payable_id}/schedule",
    response_model=PaymentScheduleRead,
    status_code=201,
    summary="Programar un pago sin mover dinero",
)
async def post_payment_schedule(
    payable_id: uuid.UUID,
    data: PaymentScheduleCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def schedule() -> tuple[str, dict[str, object]]:
        item = await payables.schedule_payment(session, context, payable_id=payable_id, data=data)
        response = PaymentScheduleRead.model_validate(item).model_dump(mode="json", by_alias=True)
        return str(item.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="payables.schedule_payment",
        idempotency_key=idempotency_key,
        request_payload={"payable_id": str(payable_id), **data.model_dump(mode="json")},
        action="supplier_payment.scheduled",
        entity_type="supplier_payment_schedule",
        callback=schedule,
    )


@router.get(
    "/expense-rules",
    response_model=list[ExpenseRuleRead],
    summary="Listar reglas para reconocer gastos bancarios",
)
async def get_expense_rules(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:read"))],
) -> list[ExpenseRuleRead]:
    items = await payables.list_rules(session, tenant_id=context.tenant_id)
    return [ExpenseRuleRead.model_validate(item) for item in items]


@router.post(
    "/expense-rules",
    response_model=ExpenseRuleRead,
    status_code=201,
    summary="Crear una regla de reconocimiento de gastos",
)
async def post_expense_rule(
    data: ExpenseRuleCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("payables:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        item = await payables.create_rule(session, context, data)
        response = ExpenseRuleRead.model_validate(item).model_dump(mode="json", by_alias=True)
        return str(item.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="expense_rules.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="expense_rule.created",
        entity_type="expense_recognition_rule",
        callback=create,
    )


def _parse_allocations(value: str | None) -> list[BankDebitAllocationInput]:
    if not value:
        return []
    try:
        raw = json.loads(value)
        return TypeAdapter(list[BankDebitAllocationInput]).validate_python(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Invalid debit allocations") from exc


@router.post(
    "/finance/bank-statements",
    response_model=BankStatementImportRead,
    summary="Conciliar un extracto con CxC y CxP",
)
async def post_finance_bank_statement(
    file: Annotated[UploadFile, File()],
    period: Annotated[str, Form(pattern=r"^\d{4}-\d{2}$")],
    session: Session,
    context: Annotated[
        AuthContext,
        Depends(require_scopes("receivables:write", "payables:write")),
    ],
    apply: Annotated[bool, Form()] = False,
    debit_allocations: Annotated[str | None, Form(alias="debitAllocations")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    try:
        period_date = datetime.strptime(period, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Period must use YYYY-MM") from exc
    allocations = _parse_allocations(debit_allocations)
    content = await file.read(bank_reconciliation.MAX_BANK_STATEMENT_BYTES + 1)
    file_name = file.filename or "estado-bancario.txt"
    if not apply:
        result = await bank_reconciliation.import_bank_statement(
            session,
            context=context,
            file_name=file_name,
            content=content,
            period=period_date,
            apply=False,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=f"preview-{uuid.uuid4()}",
            debit_allocations=allocations,
            process_debits=True,
        )
        return result.model_dump(mode="json", by_alias=True)
    if idempotency_key is None or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(
            status_code=422,
            detail="An Idempotency-Key between 16 and 128 characters is required",
        )

    async def reconcile() -> tuple[str, dict[str, object]]:
        result = await bank_reconciliation.import_bank_statement(
            session,
            context=context,
            file_name=file_name,
            content=content,
            period=period_date,
            apply=True,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            debit_allocations=allocations,
            process_debits=True,
        )
        return str(context.tenant_id), result.model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="finance.bank_statement.reconcile",
        idempotency_key=idempotency_key,
        request_payload={
            "file_name": file_name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "period": period,
            "debit_allocations": [item.model_dump(mode="json") for item in allocations],
        },
        action="bank_statement.reconciled",
        entity_type="bank_statement_import",
        callback=reconcile,
    )

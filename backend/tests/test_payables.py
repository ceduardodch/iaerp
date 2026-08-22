from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.analytics import AnalyticAssignment
from app.models.payables import (
    BankTransactionAllocation,
    PayableMovement,
    SupplierPaymentSchedule,
)
from app.models.platform import AuditEvent, OutboxEvent
from app.models.tax import FiscalDocument, TaxPeriod
from tests.test_bank_statement_import import _row, _statement
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for
from tests.test_receivables_payments_api import _create_receivable_via_event


async def _create_payable(
    client,
    token: str,
    *,
    timing: str,
    total: str,
    tax_classification: str = "DEDUCTIBLE_PENDING_REVIEW",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/payables",
        headers=auth(token, f"create-payable-{timing.lower()}-{total}"),
        json={
            "supplierName": "Gasolinera Ejemplo",
            "description": "Combustible del vehículo",
            "category": "Combustible",
            "issueDate": "2026-01-10",
            "dueDate": "2026-01-31",
            "total": total,
            "paymentTiming": timing,
            "paymentDate": "2026-01-10",
            "paymentMethod": "TRANSFER",
            "taxClassification": tax_classification,
            "evidenceStatus": "NONE",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_fiscal_purchase(
    *,
    sequential: str,
    total: str = "115.00",
    issue_date: date = date(2026, 8, 1),
    supplier_name: str = "Proveedor SRI Ejemplo",
) -> uuid.UUID:
    async with SessionFactory.begin() as session:
        document = FiscalDocument(
            tenant_id=TENANT_A,
            direction="RECIBIDO",
            doc_type="FACTURA",
            access_key=sequential.zfill(49),
            authorization_number=sequential.zfill(49),
            issue_date=issue_date,
            establishment_code="001",
            emission_point_code="001",
            sequential=sequential.zfill(9),
            counterparty_identification="1799999999001",
            counterparty_name=supplier_name,
            subtotal=Decimal("100.00"),
            tax_total=Decimal(total) - Decimal("100.00"),
            total=Decimal(total),
            payment_methods=["20"],
            is_preliminary=False,
        )
        session.add(document)
        await session.flush()
        return document.id


async def test_sri_review_links_classifies_tags_and_records_paid_expense(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["analytics:write", "payables:extract", "payables:read", "payables:write"],
    )
    classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=auth(token, "sri-review-classification-0001"),
        json={"code": "PROYECTO_SRI", "name": "Proyecto SRI", "maxDepth": 1},
    )
    assert classification.status_code == 201, classification.text
    value = await client.post(
        f"/api/v1/analytic-classifications/{classification.json()['id']}/values",
        headers=auth(token, "sri-review-value-0001"),
        json={"code": "IAERP", "name": "IAERP"},
    )
    assert value.status_code == 201, value.text
    document_id = await _create_fiscal_purchase(sequential="810000001")
    payload = {
        "documentId": str(document_id),
        "taxClassification": "DEDUCTIBLE_CONFIRMED",
        "analyticValueIds": [value.json()["id"]],
        "paymentState": "PAID",
        "paymentDate": "2026-08-05",
        "paymentMethod": "TRANSFER",
        "paymentReference": "PAGO SRI 001",
    }

    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-paid-0001"),
        json=payload,
    )
    assert reviewed.status_code == 201, reviewed.text
    body = reviewed.json()
    assert body["fiscalDocumentId"] == str(document_id)
    assert body["taxClassification"] == "DEDUCTIBLE_CONFIRMED"
    assert body["status"] == "SETTLED"
    assert body["openAmount"] == "0.00"
    assert body["analyticAssignments"][0]["valueId"] == value.json()["id"]

    replay = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-paid-0001"),
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == body

    async with SessionFactory() as session:
        movements = list(
            await session.scalars(
                select(PayableMovement).where(PayableMovement.payable_id == uuid.UUID(body["id"]))
            )
        )
        assignments = list(
            await session.scalars(
                select(AnalyticAssignment).where(
                    AnalyticAssignment.target_id == uuid.UUID(body["id"])
                )
            )
        )
    assert len(movements) == 1
    assert movements[0].effective_date == date(2026, 8, 5)
    assert len(assignments) == 1


async def test_sri_review_can_schedule_non_deductible_expense(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000002")
    linked = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "sri-review-prelinked-0001"),
        json={"documentId": str(document_id)},
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["taxClassification"] == "DEDUCTIBLE_PENDING_REVIEW"
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-scheduled-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "NON_DEDUCTIBLE",
            "paymentState": "SCHEDULED",
            "scheduledDate": "2026-08-31",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    body = reviewed.json()
    assert body["status"] == "OPEN"
    assert body["dueDate"] == "2026-08-31"
    assert body["taxClassification"] == "NON_DEDUCTIBLE"

    async with SessionFactory() as session:
        schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(body["id"])
            )
        )
    assert schedule is not None
    assert schedule.scheduled_date == date(2026, 8, 31)
    assert schedule.amount == Decimal("115.00")


async def test_payable_fiscal_use_can_be_corrected_with_reason_and_audit(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000020")
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-correction-source-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "NON_DEDUCTIBLE",
            "internalClassification": "DECLARATION_ONLY",
            "paymentState": "UNCONFIRMED",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    payable_id = reviewed.json()["id"]
    payload = {
        "taxClassification": "DEDUCTIBLE_CONFIRMED",
        "internalClassification": "REAL",
        "reason": "Se confirmó que corresponde al servicio contratado",
        "analyticValueIds": [],
    }

    corrected = await client.put(
        f"/api/v1/payables/{payable_id}/classification",
        headers=auth(token, "payable-fiscal-correction-0001"),
        json=payload,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["taxClassification"] == "DEDUCTIBLE_CONFIRMED"
    assert corrected.json()["internalClassification"] == "REAL"
    replay = await client.put(
        f"/api/v1/payables/{payable_id}/classification",
        headers=auth(token, "payable-fiscal-correction-0001"),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == corrected.json()

    async with SessionFactory() as session:
        audit_events = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A,
                    AuditEvent.action == "payable.classification_updated",
                    AuditEvent.entity_id == payable_id,
                )
            )
        )
    assert len(audit_events) == 1
    assert audit_events[0].details["reason"] == payload["reason"]
    assert (
        audit_events[0].details["tax_classification"]
        == "DEDUCTIBLE_CONFIRMED"
    )
    assert audit_events[0].details["internal_classification"] == "REAL"


async def test_payable_fiscal_use_cannot_change_after_period_is_declared(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(
        sequential="810000021",
        issue_date=date(2024, 11, 10),
    )
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-declared-source-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "NON_DEDUCTIBLE",
            "internalClassification": "DECLARATION_ONLY",
            "paymentState": "UNCONFIRMED",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    async with SessionFactory.begin() as session:
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2024,
            month=11,
            obligation_type="IVA",
            status="DECLARADO",
        )
        session.add(period)
        await session.flush()
        document = await session.get(FiscalDocument, document_id)
        assert document is not None
        document.tax_period_id = period.id

    blocked = await client.put(
        f"/api/v1/payables/{reviewed.json()['id']}/classification",
        headers=auth(token, "payable-fiscal-declared-0001"),
        json={
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "reason": "Corrección posterior",
            "analyticValueIds": [],
        },
    )
    assert blocked.status_code == 409
    assert "periodo declarado" in blocked.json()["detail"]

    internal_change = await client.put(
        f"/api/v1/payables/{reviewed.json()['id']}/classification",
        headers=auth(token, "payable-internal-declared-0001"),
        json={
            "taxClassification": "NON_DEDUCTIBLE",
            "internalClassification": "REAL",
            "reason": None,
            "analyticValueIds": [],
        },
    )
    assert internal_change.status_code == 200, internal_change.text
    assert internal_change.json()["taxClassification"] == "NON_DEDUCTIBLE"
    assert internal_change.json()["internalClassification"] == "REAL"


async def test_payables_can_be_classified_in_bulk_and_replayed(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write"],
    )
    first = await _create_payable(client, token, timing="PAY_LATER", total="35.00")
    second = await _create_payable(
        client,
        token,
        timing="PAY_LATER",
        total="65.00",
        tax_classification="NON_DEDUCTIBLE",
    )
    payload = {
        "payableIds": [first["id"], second["id"]],
        "taxClassification": "DEDUCTIBLE_CONFIRMED",
        "internalClassification": "REAL",
        "reason": "Revisión conjunta de compras",
        "analyticChange": "REPLACE",
        "analyticValueIds": [],
    }

    updated = await client.put(
        "/api/v1/payables/classifications/bulk",
        headers=auth(token, "payable-bulk-classification-0001"),
        json=payload,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updatedCount"] == 2
    assert updated.json()["failedCount"] == 0
    assert {item["status"] for item in updated.json()["items"]} == {"UPDATED"}

    replay = await client.put(
        "/api/v1/payables/classifications/bulk",
        headers=auth(token, "payable-bulk-classification-0001"),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == updated.json()

    different_payload = await client.put(
        "/api/v1/payables/classifications/bulk",
        headers=auth(token, "payable-bulk-classification-0001"),
        json={
            **payload,
            "payableIds": [first["id"]],
            "internalClassification": "DECLARATION_ONLY",
        },
    )
    assert different_payload.status_code == 409
    assert "different request" in different_payload.json()["detail"]

    for payable_id in (first["id"], second["id"]):
        item = await client.get(f"/api/v1/payables/{payable_id}", headers=auth(token))
        assert item.json()["taxClassification"] == "DEDUCTIBLE_CONFIRMED"
        assert item.json()["internalClassification"] == "REAL"


async def test_bulk_internal_change_does_not_require_resolving_pending_fiscal_use(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write"],
    )
    payable = await _create_payable(client, token, timing="PAY_LATER", total="40.00")
    updated = await client.put(
        "/api/v1/payables/classifications/bulk",
        headers=auth(token, "payable-bulk-internal-only-0001"),
        json={
            "payableIds": [payable["id"]],
            "internalClassification": "DECLARATION_ONLY",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updatedCount"] == 1
    item = await client.get(f"/api/v1/payables/{payable['id']}", headers=auth(token))
    assert item.json()["taxClassification"] == "DEDUCTIBLE_PENDING_REVIEW"
    assert item.json()["internalClassification"] == "DECLARATION_ONLY"


async def test_sri_review_requires_both_extract_and_write_scopes(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000003")
    denied = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-review-scope-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentState": "UNCONFIRMED",
        },
    )
    assert denied.status_code == 403
    bulk_denied = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-review-scope-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
        },
    )
    assert bulk_denied.status_code == 403


async def test_sri_review_preserves_payment_and_tags_after_a_movement(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["analytics:write", "payables:extract", "payables:read", "payables:write"],
    )
    classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=auth(token, "sri-existing-classification-0001"),
        json={"code": "SUCURSAL_SRI", "name": "Sucursal SRI", "maxDepth": 1},
    )
    value = await client.post(
        f"/api/v1/analytic-classifications/{classification.json()['id']}/values",
        headers=auth(token, "sri-existing-value-0001"),
        json={"code": "NORTE", "name": "Norte"},
    )
    document_id = await _create_fiscal_purchase(sequential="810000004")
    linked = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "sri-existing-link-0001"),
        json={"documentId": str(document_id)},
    )
    payable_id = linked.json()["id"]
    tagged = await client.put(
        f"/api/v1/payables/{payable_id}/analytic-assignments",
        headers=auth(token, "sri-existing-tags-0001"),
        json={"valueIds": [value.json()["id"]]},
    )
    assert tagged.status_code == 200, tagged.text
    payment = await client.post(
        f"/api/v1/payables/{payable_id}/payments",
        headers=auth(token, "sri-existing-payment-0001"),
        json={"amount": "40.00", "paymentDate": "2026-08-06", "method": "TRANSFER"},
    )
    assert payment.status_code == 201, payment.text

    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-existing-review-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "NON_DEDUCTIBLE",
            "analyticValueIds": [],
            "paymentState": "KEEP_EXISTING",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["status"] == "PARTIAL"
    assert reviewed.json()["openAmount"] == "75.00"
    assert reviewed.json()["taxClassification"] == "NON_DEDUCTIBLE"
    assert reviewed.json()["analyticAssignments"][0]["valueId"] == value.json()["id"]


async def test_sri_bulk_review_is_idempotent_and_protects_existing_movements(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    new_document_id = await _create_fiscal_purchase(sequential="810000008")
    partial_document_id = await _create_fiscal_purchase(sequential="810000009")
    reviewed_document_id = await _create_fiscal_purchase(sequential="810000010")

    linked = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "sri-bulk-link-partial-0001"),
        json={"documentId": str(partial_document_id)},
    )
    assert linked.status_code == 201, linked.text
    partial_payable_id = linked.json()["id"]
    partial_payment = await client.post(
        f"/api/v1/payables/{partial_payable_id}/payments",
        headers=auth(token, "sri-bulk-payment-partial-0001"),
        json={"amount": "40.00", "paymentDate": "2026-08-06", "method": "TRANSFER"},
    )
    assert partial_payment.status_code == 201, partial_payment.text

    already_reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-bulk-already-reviewed-0001"),
        json={
            "documentId": str(reviewed_document_id),
            "taxClassification": "NON_DEDUCTIBLE",
            "paymentState": "UNCONFIRMED",
        },
    )
    assert already_reviewed.status_code == 201, already_reviewed.text

    payload = {
        "documentIds": [
            str(new_document_id),
            str(partial_document_id),
            str(reviewed_document_id),
        ],
        "taxClassification": "DEDUCTIBLE_CONFIRMED",
        "analyticChange": {"mode": "KEEP_EXISTING", "valueIds": []},
        "paymentAction": "PAID",
        "paymentDate": "2026-08-08",
        "paymentMethod": "TRANSFER",
    }
    bulk = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-review-00000001"),
        json=payload,
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["reviewedCount"] == 1
    assert bulk.json()["protectedCount"] == 1
    assert bulk.json()["skippedCount"] == 1
    assert bulk.json()["failedCount"] == 0
    statuses = {item["documentId"]: item["status"] for item in bulk.json()["items"]}
    assert statuses[str(new_document_id)] == "REVIEWED"
    assert statuses[str(partial_document_id)] == "PROTECTED"
    assert statuses[str(reviewed_document_id)] == "SKIPPED"

    replay = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-review-00000001"),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == bulk.json()

    new_payable_id = next(
        item["payableId"]
        for item in bulk.json()["items"]
        if item["documentId"] == str(new_document_id)
    )
    async with SessionFactory() as session:
        movements = list(
            await session.scalars(
                select(PayableMovement).where(
                    PayableMovement.movement_type == "PAYMENT",
                    PayableMovement.payable_id.in_(
                        [uuid.UUID(new_payable_id), uuid.UUID(partial_payable_id)]
                    ),
                )
            )
        )
        audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A,
                    AuditEvent.action == "payable.document_reviewed",
                    AuditEvent.entity_id.in_([new_payable_id, partial_payable_id]),
                )
            )
        )
        outbox = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == TENANT_A,
                    OutboxEvent.event_type == "payable.document_reviewed",
                    OutboxEvent.aggregate_id.in_([new_payable_id, partial_payable_id]),
                )
            )
        )
    assert len(movements) == 2
    assert len(audits) == 2
    assert len(outbox) == 2


async def test_sri_bulk_safe_default_preserves_an_existing_payment_schedule(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000011")
    linked = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "sri-bulk-schedule-link-0001"),
        json={"documentId": str(document_id)},
    )
    assert linked.status_code == 201, linked.text
    payable_id = linked.json()["id"]
    scheduled = await client.post(
        f"/api/v1/payables/{payable_id}/schedule",
        headers=auth(token, "sri-bulk-schedule-create-0001"),
        json={"scheduledDate": "2026-08-30", "amount": "115.00", "priority": "NORMAL"},
    )
    assert scheduled.status_code == 201, scheduled.text

    reviewed = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-schedule-review-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentAction": "KEEP_EXISTING_OR_UNCONFIRMED",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewedCount"] == 1

    async with SessionFactory() as session:
        schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(payable_id)
            )
        )
    assert schedule is not None
    assert schedule.status == "SCHEDULED"
    assert schedule.scheduled_date == date(2026, 8, 30)
    assert schedule.amount == Decimal("115.00")


async def test_sri_bulk_reconciles_manual_purchase_without_losing_tags_or_schedule(
    client,
) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["analytics:write", "payables:extract", "payables:read", "payables:write"],
    )
    classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=auth(token, "sri-bulk-manual-classification-0001"),
        json={"code": "MANUAL_SRI", "name": "Manual SRI", "maxDepth": 1},
    )
    value = await client.post(
        f"/api/v1/analytic-classifications/{classification.json()['id']}/values",
        headers=auth(token, "sri-bulk-manual-value-0001"),
        json={"code": "CENTRO", "name": "Centro"},
    )
    manual = await _create_payable(client, token, timing="PAY_LATER", total="115.00")
    tagged = await client.put(
        f"/api/v1/payables/{manual['id']}/analytic-assignments",
        headers=auth(token, "sri-bulk-manual-tags-0001"),
        json={"valueIds": [value.json()["id"]]},
    )
    assert tagged.status_code == 200, tagged.text
    scheduled = await client.post(
        f"/api/v1/payables/{manual['id']}/schedule",
        headers=auth(token, "sri-bulk-manual-schedule-0001"),
        json={"scheduledDate": "2026-02-15", "amount": "115.00", "priority": "NORMAL"},
    )
    assert scheduled.status_code == 201, scheduled.text
    document_id = await _create_fiscal_purchase(
        sequential="810000012",
        issue_date=date(2026, 1, 10),
        supplier_name="Gasolinera Ejemplo",
    )

    reviewed = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-manual-review-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentAction": "KEEP_EXISTING_OR_UNCONFIRMED",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewedCount"] == 1
    assert reviewed.json()["items"][0]["payableId"] == manual["id"]

    async with SessionFactory() as session:
        schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(str(manual["id"]))
            )
        )
        assignments = list(
            await session.scalars(
                select(AnalyticAssignment).where(
                    AnalyticAssignment.target_id == uuid.UUID(str(manual["id"]))
                )
            )
        )
    assert schedule is not None
    assert schedule.status == "SCHEDULED"
    assert schedule.scheduled_date == date(2026, 2, 15)
    assert [str(item.value_id) for item in assignments] == [value.json()["id"]]


async def test_sri_bulk_protects_reconciled_manual_purchase_with_partial_payment(
    client,
) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["analytics:write", "payables:extract", "payables:read", "payables:write"],
    )
    classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=auth(token, "sri-bulk-protected-classification-0001"),
        json={"code": "PROTECTED_SRI", "name": "Protegida SRI", "maxDepth": 1},
    )
    value = await client.post(
        f"/api/v1/analytic-classifications/{classification.json()['id']}/values",
        headers=auth(token, "sri-bulk-protected-value-0001"),
        json={"code": "ORIGINAL", "name": "Original"},
    )
    manual = await _create_payable(client, token, timing="PAY_LATER", total="115.00")
    tagged = await client.put(
        f"/api/v1/payables/{manual['id']}/analytic-assignments",
        headers=auth(token, "sri-bulk-protected-tags-0001"),
        json={"valueIds": [value.json()["id"]]},
    )
    assert tagged.status_code == 200, tagged.text
    payment = await client.post(
        f"/api/v1/payables/{manual['id']}/payments",
        headers=auth(token, "sri-bulk-protected-payment-0001"),
        json={"amount": "40.00", "paymentDate": "2026-01-20", "method": "TRANSFER"},
    )
    assert payment.status_code == 201, payment.text
    document_id = await _create_fiscal_purchase(
        sequential="810000013",
        issue_date=date(2026, 1, 10),
        supplier_name="Gasolinera Ejemplo",
    )

    reviewed = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-protected-review-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "NON_DEDUCTIBLE",
            "analyticChange": {"mode": "KEEP_EXISTING", "valueIds": []},
            "paymentAction": "PAID",
            "paymentDate": "2026-01-25",
            "paymentMethod": "TRANSFER",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["protectedCount"] == 1
    assert reviewed.json()["failedCount"] == 0
    assert reviewed.json()["items"][0]["payableId"] == manual["id"]

    payable = await client.get(f"/api/v1/payables/{manual['id']}", headers=auth(token))
    assert payable.status_code == 200, payable.text
    assert payable.json()["openAmount"] == "75.00"
    assert payable.json()["taxClassification"] == "NON_DEDUCTIBLE"
    assert payable.json()["analyticAssignments"][0]["valueId"] == value.json()["id"]


async def test_sri_bulk_links_manual_purchase_that_was_already_classified(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    manual = await _create_payable(
        client,
        token,
        timing="PAY_LATER",
        total="115.00",
        tax_classification="NON_DEDUCTIBLE",
    )
    document_id = await _create_fiscal_purchase(
        sequential="810000015",
        issue_date=date(2026, 1, 10),
        supplier_name="Gasolinera Ejemplo",
    )

    reviewed = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-classified-manual-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentAction": "PAID",
            "paymentDate": "2026-01-25",
            "paymentMethod": "TRANSFER",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["skippedCount"] == 1
    assert reviewed.json()["failedCount"] == 0
    assert reviewed.json()["items"][0]["payableId"] == manual["id"]

    payable = await client.get(f"/api/v1/payables/{manual['id']}", headers=auth(token))
    assert payable.status_code == 200, payable.text
    assert payable.json()["fiscalDocumentId"] == str(document_id)
    assert payable.json()["taxClassification"] == "NON_DEDUCTIBLE"
    assert payable.json()["openAmount"] == "115.00"


async def test_sri_bulk_rejects_apply_without_tags(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000014")
    response = await client.post(
        "/api/v1/payables/from-document/reviews",
        headers=auth(token, "sri-bulk-empty-tags-0001"),
        json={
            "documentIds": [str(document_id)],
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "analyticChange": {"mode": "APPLY", "valueIds": []},
        },
    )
    assert response.status_code == 422


async def test_sri_review_cancels_active_schedule_when_marked_paid(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000005")
    linked = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "sri-schedule-link-0001"),
        json={"documentId": str(document_id)},
    )
    payable_id = linked.json()["id"]
    scheduled = await client.post(
        f"/api/v1/payables/{payable_id}/schedule",
        headers=auth(token, "sri-existing-schedule-0001"),
        json={"scheduledDate": "2026-08-30", "amount": "115.00", "priority": "NORMAL"},
    )
    assert scheduled.status_code == 201, scheduled.text
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-schedule-paid-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentState": "PAID",
            "paymentDate": "2026-08-08",
            "paymentMethod": "TRANSFER",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["status"] == "SETTLED"

    async with SessionFactory() as session:
        schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(payable_id)
            )
        )
    assert schedule is not None
    assert schedule.status == "CANCELLED"


async def test_normal_payment_cancels_schedule_created_by_sri_review(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000007")
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-scheduled-review-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentState": "SCHEDULED",
            "scheduledDate": "2026-08-31",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    payable_id = reviewed.json()["id"]
    partial = await client.post(
        f"/api/v1/payables/{payable_id}/payments",
        headers=auth(token, "sri-scheduled-payment-partial-0001"),
        json={
            "amount": "40.00",
            "paymentDate": "2026-08-20",
            "method": "TRANSFER",
        },
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["status"] == "PARTIAL"
    async with SessionFactory() as session:
        partial_schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(payable_id)
            )
        )
    assert partial_schedule is not None
    assert partial_schedule.status == "SCHEDULED"
    assert partial_schedule.amount == Decimal("75.00")

    paid = await client.post(
        f"/api/v1/payables/{payable_id}/payments",
        headers=auth(token, "sri-scheduled-payment-final-0001"),
        json={
            "amount": "75.00",
            "paymentDate": "2026-08-21",
            "method": "TRANSFER",
        },
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["status"] == "SETTLED"

    async with SessionFactory() as session:
        schedule = await session.scalar(
            select(SupplierPaymentSchedule).where(
                SupplierPaymentSchedule.payable_id == uuid.UUID(payable_id)
            )
        )
    assert schedule is not None
    assert schedule.status == "CANCELLED"


async def test_sri_review_keeps_unknown_due_date_out_of_due_filter(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:extract", "payables:read", "payables:write"],
    )
    document_id = await _create_fiscal_purchase(sequential="810000006")
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "sri-unknown-date-0001"),
        json={
            "documentId": str(document_id),
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentState": "UNCONFIRMED",
        },
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["dueDate"] is None

    due = await client.get(
        "/api/v1/payables?dueBefore=2026-12-31",
        headers=auth(token),
    )
    assert due.status_code == 200, due.text
    assert reviewed.json()["id"] not in {item["id"] for item in due.json()}


async def test_paid_now_and_pay_later_share_the_same_purchase_flow(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write"],
    )
    paid = await _create_payable(client, token, timing="PAID_NOW", total="35.00")
    assert paid["status"] == "SETTLED"
    assert paid["openAmount"] == "0.00"
    assert paid["taxClassification"] == "DEDUCTIBLE_PENDING_REVIEW"
    assert paid["evidenceStatus"] == "NONE"

    pending = await _create_payable(client, token, timing="PAY_LATER", total="100.00")
    assert pending["status"] == "OPEN"
    payment = await client.post(
        f"/api/v1/payables/{pending['id']}/payments",
        headers=auth(token, "payable-partial-payment-0001"),
        json={
            "amount": "40.00",
            "paymentDate": "2026-01-20",
            "method": "TRANSFER",
            "reference": "PAGO PROVEEDOR 001",
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["status"] == "PARTIAL"
    assert payment.json()["openAmount"] == "60.00"

    movements = await client.get(f"/api/v1/payables/{pending['id']}/movements", headers=auth(token))
    assert movements.status_code == 200, movements.text
    assert len(movements.json()) == 1
    movement_id = movements.json()[0]["id"]
    reversal = await client.post(
        f"/api/v1/payables/{pending['id']}/movements/{movement_id}/reversal",
        headers=auth(token, "payable-payment-reversal-0001"),
        json={"reason": "Pago registrado en la cuenta equivocada", "effectiveDate": "2026-01-21"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["status"] == "OPEN"
    assert reversal.json()["openAmount"] == "100.00"


async def test_payables_are_tenant_scoped(client) -> None:
    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write"],
    )
    await _create_payable(client, token_a, timing="PAY_LATER", total="25.00")
    token_b = await token_for(
        client,
        "b@iaerp.local",
        TENANT_B,
        ["payables:read"],
    )
    response = await client.get("/api/v1/payables", headers=auth(token_b))
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_payable_adjustments_schedule_and_reversal_keep_separate_history(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["payables:read", "payables:write"],
    )
    payable = await _create_payable(client, token, timing="PAY_LATER", total="100.00")
    retention = await client.post(
        f"/api/v1/payables/{payable['id']}/adjustments",
        headers=auth(token, "payable-retention-0001"),
        json={
            "movementType": "RETENTION",
            "amount": "10.00",
            "effectiveDate": "2026-01-18",
            "reference": "RET-001-001-000000123",
        },
    )
    assert retention.status_code == 201, retention.text
    assert retention.json()["openAmount"] == "90.00"
    credit_note = await client.post(
        f"/api/v1/payables/{payable['id']}/adjustments",
        headers=auth(token, "payable-credit-note-0001"),
        json={
            "movementType": "CREDIT_NOTE",
            "amount": "20.00",
            "effectiveDate": "2026-01-19",
            "reference": "NC-001-001-000000456",
        },
    )
    assert credit_note.status_code == 201, credit_note.text
    assert credit_note.json()["openAmount"] == "70.00"
    schedule = await client.post(
        f"/api/v1/payables/{payable['id']}/schedule",
        headers=auth(token, "payable-schedule-0001"),
        json={"scheduledDate": "2026-01-25", "amount": "50.00", "priority": "HIGH"},
    )
    assert schedule.status_code == 201, schedule.text
    assert schedule.json()["status"] == "SCHEDULED"
    over_schedule = await client.post(
        f"/api/v1/payables/{payable['id']}/schedule",
        headers=auth(token, "payable-schedule-over-0001"),
        json={"scheduledDate": "2026-01-25", "amount": "80.00", "priority": "NORMAL"},
    )
    assert over_schedule.status_code == 422

    movements = await client.get(f"/api/v1/payables/{payable['id']}/movements", headers=auth(token))
    retention_movement = next(
        item for item in movements.json() if item["movementType"] == "RETENTION"
    )
    reversal = await client.post(
        f"/api/v1/payables/{payable['id']}/movements/{retention_movement['id']}/reversal",
        headers=auth(token, "payable-retention-reversal-0001"),
        json={"reason": "Retención anulada por el proveedor", "effectiveDate": "2026-01-20"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["openAmount"] == "80.00"
    history = await client.get(f"/api/v1/payables/{payable['id']}/movements", headers=auth(token))
    assert {item["movementType"] for item in history.json()} == {
        "RETENTION",
        "CREDIT_NOTE",
        "REVERSAL",
    }


async def test_one_statement_reconciles_receivable_credit_and_payable_debit(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="bank-both-sides",
        sequential="000000975",
        total=Decimal("80.00"),
        issue_date=date(2026, 1, 1),
    )
    receivable_id, _masters = await setup(client)
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:write", "payables:read", "payables:write"],
    )
    payable = await _create_payable(client, token, timing="PAY_LATER", total="45.00")
    content = _statement(
        _row(
            occurred_at="01/14/2026 13:32:00.000",
            reference="COBRO-001",
            description="TRANSF BCE RECIBIDA",
            sign="+",
            amount="80.00",
        ),
        _row(
            occurred_at="01/15/2026 10:10:00.000",
            reference="PAGO-001",
            description="TRANSFERENCIA GASOLINERA EJEMPLO",
            sign="-",
            amount="45.00",
        ),
    )
    preview = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["matchedCount"] == 1
    assert body["payableMatchedCount"] == 1
    assert body["debitRows"] == 1
    assert body["ignoredDebitCount"] == 0
    assert body["debitMatches"][0]["payableId"] == payable["id"]

    applied = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token, "bank-both-sides-register-0001"),
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["matches"][0]["status"] == "REGISTERED"
    assert result["debitMatches"][0]["status"] == "REGISTERED"
    payable_after = await client.get(f"/api/v1/payables/{payable['id']}", headers=auth(token))
    assert payable_after.json()["status"] == "SETTLED"

    async with SessionFactory() as session:
        allocations = list(await session.scalars(BankTransactionAllocation.__table__.select()))
        payable_payments = list(await session.scalars(PayableMovement.__table__.select()))
    assert len(allocations) == 2
    assert len(payable_payments) == 1
    assert str(result["matches"][0]["receivableId"]) == receivable_id


async def test_unmatched_debit_uses_rule_but_never_creates_expense(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:write", "payables:read", "payables:write"],
    )
    rule = await client.post(
        "/api/v1/expense-rules",
        headers=auth(token, "expense-rule-gasoline-0001"),
        json={
            "name": "Gasolineras",
            "descriptionPattern": "GASOLINERA",
            "category": "Combustible",
            "supplierName": "Gasolinera sugerida",
        },
    )
    assert rule.status_code == 201, rule.text
    content = _statement(
        _row(
            occurred_at="01/18/2026 08:00:00.000",
            reference="DEBITO-002",
            description="CONSUMO GASOLINERA NORTE",
            sign="-",
            amount="22.50",
        )
    )
    preview = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["payableMatchedCount"] == 0
    assert body["ruleSuggestionCount"] == 1
    assert body["debitSuggestions"][0]["classification"] == "EXPENSE_CANDIDATE"
    assert body["debitSuggestions"][0]["suggestedCategory"] == "Combustible"
    payables = await client.get("/api/v1/payables", headers=auth(token))
    assert payables.json() == []


async def test_one_debit_can_be_split_manually_across_payables(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:write", "payables:read", "payables:write"],
    )
    first = await _create_payable(client, token, timing="PAY_LATER", total="30.00")
    second = await _create_payable(client, token, timing="PAY_LATER", total="20.00")
    content = _statement(
        _row(
            occurred_at="01/22/2026 09:30:00.000",
            reference="PAGO-LOTE-001",
            description="TRANSFERENCIA A PROVEEDORES",
            sign="-",
            amount="50.00",
        )
    )
    preview = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    transaction_id = preview.json()["debitSuggestions"][0]["transactionId"]
    allocations = json.dumps(
        [
            {"transactionId": transaction_id, "payableId": first["id"], "amount": "30.00"},
            {"transactionId": transaction_id, "payableId": second["id"], "amount": "20.00"},
        ]
    )
    applied = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token, "bank-manual-debit-split-0001"),
        data={
            "apply": "true",
            "period": "2026-01",
            "debitAllocations": allocations,
        },
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["payableMatchedCount"] == 2
    for payable_id in (first["id"], second["id"]):
        item = await client.get(f"/api/v1/payables/{payable_id}", headers=auth(token))
        assert item.json()["status"] == "SETTLED"

    async with SessionFactory() as session:
        allocation_rows = list(await session.scalars(select(BankTransactionAllocation)))
    assert len(allocation_rows) == 2


async def test_bank_links_paid_now_evidence_without_duplicate_on_reimport(client) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:write", "payables:read", "payables:write"],
    )
    payable = await _create_payable(client, token, timing="PAID_NOW", total="35.00")
    content = _statement(
        _row(
            occurred_at="01/10/2026 11:00:00.000",
            reference="PAGO-DIRECTO-001",
            description="TRANSFERENCIA GASOLINERA EJEMPLO",
            sign="-",
            amount="35.00",
        )
    )
    preview = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["debitMatches"][0]["linksExistingPayment"] is True

    applied = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token, "bank-paid-now-evidence-0001"),
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["debitMatches"][0]["status"] == "EVIDENCE_LINKED"

    repeated = await client.post(
        "/api/v1/finance/bank-statements",
        headers=auth(token, "bank-paid-now-evidence-0002"),
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["debitMatches"] == []

    movements = await client.get(f"/api/v1/payables/{payable['id']}/movements", headers=auth(token))
    assert len(movements.json()) == 1
    assert movements.json()[0]["supportReference"].startswith("BANCO PAGO-DIRECTO-001")
    async with SessionFactory() as session:
        allocation_rows = list(await session.scalars(select(BankTransactionAllocation)))
    assert len(allocation_rows) == 1

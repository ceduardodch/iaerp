from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.payables import BankTransactionAllocation, PayableMovement
from tests.test_bank_statement_import import _row, _statement
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for
from tests.test_receivables_payments_api import _create_receivable_via_event


async def _create_payable(client, token: str, *, timing: str, total: str) -> dict[str, object]:
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
            "taxClassification": "DEDUCTIBLE_PENDING_REVIEW",
            "evidenceStatus": "NONE",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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

    movements = await client.get(
        f"/api/v1/payables/{pending['id']}/movements", headers=auth(token)
    )
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

    movements = await client.get(
        f"/api/v1/payables/{payable['id']}/movements", headers=auth(token)
    )
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
    history = await client.get(
        f"/api/v1/payables/{payable['id']}/movements", headers=auth(token)
    )
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
    payable_after = await client.get(
        f"/api/v1/payables/{payable['id']}", headers=auth(token)
    )
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
        allocation_rows = list(
            await session.scalars(select(BankTransactionAllocation))
        )
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

    movements = await client.get(
        f"/api/v1/payables/{payable['id']}/movements", headers=auth(token)
    )
    assert len(movements.json()) == 1
    assert movements.json()[0]["supportReference"].startswith("BANCO PAGO-DIRECTO-001")
    async with SessionFactory() as session:
        allocation_rows = list(
            await session.scalars(select(BankTransactionAllocation))
        )
    assert len(allocation_rows) == 1

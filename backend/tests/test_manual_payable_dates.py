import uuid
from datetime import date

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.payables import PayableInstallment
from app.models.platform import AuditEvent
from tests.test_billing_api import TENANT_A, TENANT_B, auth, token_for


async def test_manual_purchase_keeps_document_due_date_separate_from_payment(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["payables:read", "payables:write"])
    payload = {
        "description": "Servicio de ejemplo",
        "issueDate": "2026-03-01",
        "total": "120.00",
        "paymentTiming": "PAID_NOW",
        "paymentDate": "2026-04-03",
        "paymentMethod": "TRANSFER",
    }
    base = "/api/v1/payables"
    unknown = await client.post(base, headers=auth(token, "unknown-due-date-001"), json=payload)
    assert unknown.status_code == 201
    assert unknown.json()["dueDate"] is None
    headers = auth(token)
    cutoff = await client.get(base, params={"dueBefore": "2026-04-30"}, headers=headers)
    assert cutoff.json() == []

    # Old clients could save an issue date as an explicit contractual due date.
    payload["dueDate"] = payload["issueDate"]
    created = await client.post(base, headers=auth(token, "legacy-due-date-001"), json=payload)
    assert created.status_code == 201
    payable_id = created.json()["id"]
    path = f"{base}/{payable_id}"
    history = (await client.get(f"{path}/movements", headers=headers)).json()
    assert len(history) == 1 and history[0]["effectiveDate"] == payload["paymentDate"]

    correction = {
        "previousDueDate": payload["issueDate"],
        "dueDate": "2026-03-31",
        "reason": "Fecha acordada en la factura",
    }
    update_headers = auth(token, "correct-due-date-001")
    result = await client.put(f"{path}/due-date", headers=update_headers, json=correction)
    assert result.status_code == 200, result.text
    assert result.json() == {**created.json(), "dueDate": "2026-03-31"}
    assert result.json()["openAmount"] == "0.00"
    replay = await client.put(f"{path}/due-date", headers=update_headers, json=correction)
    assert replay.json() == result.json()
    conflict = await client.put(
        f"{path}/due-date",
        headers=auth(token, "stale-due-date-001"),
        json={**correction, "dueDate": "2026-04-15"},
    )
    assert conflict.status_code == 409
    other = await token_for(client, "b@iaerp.local", TENANT_B, ["payables:write"])
    hidden = await client.put(
        f"{path}/due-date", headers=auth(other, "cross-tenant-due-001"), json=correction
    )
    assert hidden.status_code == 404
    assert (await client.get(f"{path}/movements", headers=headers)).json() == history
    async with SessionFactory() as session:
        installment = await session.scalar(
            select(PayableInstallment).where(PayableInstallment.payable_id == uuid.UUID(payable_id))
        )
        assert installment.due_date == date(2026, 3, 31)
        event = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == payable_id,
                    AuditEvent.action == "payable.due_date_corrected",
                )
            )
        ).one()
        assert {key: event.details[key] for key in ["previous_due_date", "due_date", "reason"]} == {
            "previous_due_date": "2026-03-01",
            "due_date": "2026-03-31",
            "reason": correction["reason"],
        }


async def test_manual_due_date_correction_respects_installment_plan_and_write_scope(client):
    writer = await token_for(client, "a@iaerp.local", TENANT_A, ["payables:write"])
    payload = {
        "description": "Compra a plazos",
        "issueDate": "2026-01-01",
        "total": "100.00",
        "installments": [
            {"dueDate": "2026-01-31", "amount": "50.00"},
            {"dueDate": "2026-02-28", "amount": "50.00"},
        ],
    }
    created = await client.post(
        "/api/v1/payables", headers=auth(writer, "purchase-multi-dates-001"), json=payload
    )
    assert created.status_code == 201
    item = created.json()
    assert item["dueDate"] == "2026-01-31"
    path = f"/api/v1/payables/{item['id']}"
    change = {
        "previousDueDate": item["dueDate"],
        "dueDate": "2026-03-31",
        "reason": "Revisar cuotas",
    }
    reader = await token_for(client, "a@iaerp.local", TENANT_A, ["payables:read"])
    denied = await client.put(
        f"{path}/due-date", headers=auth(reader, "read-only-dates-001"), json=change
    )
    assert denied.status_code == 403
    denied = await client.put(
        f"{path}/due-date", headers=auth(writer, "multi-due-date-001"), json=change
    )
    assert denied.status_code == 409
    assert (await client.get(path, headers=auth(reader))).json() == item

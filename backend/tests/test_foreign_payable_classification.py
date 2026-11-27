"""Reclasificar una factura histórica sin duplicar su pago o deducir IVA."""

import uuid

from app.db.session import SessionFactory
from app.models.tax import TaxPeriod
from tests.test_tax_iva import auth, find_period, token_for


async def test_paid_purchase_can_be_marked_for_review_in_its_payment_month(client):
    token = await token_for(client, ["payables:write", "payables:read", "tax:read"])
    base = "/api/v1/payables"
    created = await client.post(
        base, headers=auth(token, "manual-before-classification"), json={
            "description": "Monitoreo de aplicaciones de prueba",
            "supplierName": "Proveedor ficticio", "total": "80.00", "issueDate": "2026-03-20",
            "dueDate": "2026-04-15", "paymentDate": "2026-04-13", "paymentMethod": "TRANSFER",
            "paymentTiming": "PAID_NOW",
        },
    )
    assert created.status_code == 201
    purchase = created.json()
    assert not purchase["foreignDigitalService"]
    item = f"{base}/{purchase['id']}"
    history = (await client.get(item + "/movements", headers=auth(token))).json()
    adjustment = {
        "taxClassification": "DEDUCTIBLE_PENDING_REVIEW", "foreignDigitalService": True,
        "reason": "Se verificó el comprobante del proveedor extranjero",
    }
    marked = await client.put(
        item + "/classification", headers=auth(token, "historical-external-mark"), json=adjustment
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["foreignDigitalService"]
    assert marked.json()["openAmount"] == "0.00"
    assert marked.json()["dueDate"] == "2026-04-15"
    assert (await client.get(item + "/movements", headers=auth(token))).json() == history

    period = await find_period(client, token, 2026, 4)
    assert period["status"] == "EVIDENCIA_INCOMPLETA"
    months = await client.get("/api/v1/tax/periods", headers=auth(token), params={"year": 2026})
    assert not any(p["month"] == 3 for p in months.json())
    summary = await client.get(f"/api/v1/tax/periods/{period['id']}/iva", headers=auth(token))
    assert summary.json()["requiresExternalReview"]
    assert summary.json()["amounts"]["ivaCreditoTributario"] == "0.00"
    async with SessionFactory.begin() as session:
        row = await session.get(TaxPeriod, uuid.UUID(period["id"]))
        row.status = "DECLARADO"
    correction = await client.put(
        item + "/classification", headers=auth(token, "correction-after-filing"),
        json={**adjustment, "foreignDigitalService": False},
    )
    assert correction.status_code == 409
    assert (await client.get(item, headers=auth(token))).json()["foreignDigitalService"]

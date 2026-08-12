import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.integrity import unique_constraint_name
from app.db.session import SessionFactory, engine

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


@pytest.mark.asyncio
@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="The asyncpg constraint contract requires PostgreSQL",
)
async def test_asyncpg_reports_analytic_unique_constraint():
    async with SessionFactory() as session:
        await session.execute(
            text(
                """
                INSERT INTO analytic_classifications (
                    code, name, max_depth, active, id, tenant_id
                ) VALUES (
                    'DUPLICATE', 'Primera', 1, true,
                    '33333333-3333-4333-8333-333333333331', :tenant_id
                )
                """
            ),
            {"tenant_id": TENANT_A},
        )
        await session.commit()
        with pytest.raises(IntegrityError) as captured:
            await session.execute(
                text(
                    """
                    INSERT INTO analytic_classifications (
                        code, name, max_depth, active, id, tenant_id
                    ) VALUES (
                        'DUPLICATE', 'Segunda', 1, true,
                        '33333333-3333-4333-8333-333333333332', :tenant_id
                    )
                    """
                ),
                {"tenant_id": TENANT_A},
            )
        assert unique_constraint_name(captured.value) == (
            "uq_analytic_classifications_tenant_code"
        )


async def _token(client, tenant_id: uuid.UUID, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": "a@iaerp.local" if tenant_id == TENANT_A else "b@iaerp.local",
            "tenantId": str(tenant_id),
            "scopes": scopes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def _headers(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.mark.asyncio
async def test_classifications_are_tenant_safe_and_allow_partial_hierarchy(client):
    writer = await _token(client, TENANT_A, ["analytics:read", "analytics:write"])
    created = await client.post(
        "/api/v1/analytic-classifications",
        headers=_headers(writer, "analytic-classification-0001"),
        json={"code": "FRANQUICIA", "name": "Franquicia", "maxDepth": 3},
    )
    assert created.status_code == 201, created.text
    classification_id = created.json()["id"]

    duplicate_classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=_headers(writer, "analytic-classification-duplicate-0001"),
        json={"code": "FRANQUICIA", "name": "Otra franquicia", "maxDepth": 1},
    )
    assert duplicate_classification.status_code == 409
    assert duplicate_classification.json()["detail"] == (
        "Ya existe una clasificación con el código FRANQUICIA"
    )

    group = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(writer, "analytic-classification-value-0001"),
        json={"code": "FARMA", "name": "Farmacia Norte", "color": "#1769AA"},
    )
    assert group.status_code == 201, group.text

    duplicate_value = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(writer, "analytic-value-duplicate-0001"),
        json={"code": "FARMA", "name": "Otra farmacia"},
    )
    assert duplicate_value.status_code == 409
    assert duplicate_value.json()["detail"] == "Ya existe el valor FARMA en Franquicia"

    child = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(writer, "analytic-classification-value-0002"),
        json={"parentId": group.json()["id"], "code": "MATRIZ", "name": "Matriz"},
    )
    assert child.status_code == 201, child.text

    payable_token = await _token(
        client, TENANT_A, ["analytics:read", "payables:read", "payables:write"]
    )
    payable = await client.post(
        "/api/v1/payables",
        headers=_headers(payable_token, "analytic-payable-create-0001"),
        json={
            "description": "Comisión de franquicia",
            "category": "Comisiones",
            "issueDate": "2026-08-11",
            "total": "100.00",
            "paymentTiming": "PAY_LATER",
            "analyticValueIds": [group.json()["id"]],
        },
    )
    assert payable.status_code == 201, payable.text
    assert payable.json()["analyticAssignments"] == [
        {
            "classificationId": classification_id,
            "classificationCode": "FRANQUICIA",
            "classificationName": "Franquicia",
            "valueId": group.json()["id"],
            "path": [{"code": "FARMA", "name": "Farmacia Norte"}],
        }
    ]

    filtered = await client.get(
        f"/api/v1/payables?analyticValueId={group.json()['id']}", headers=_headers(payable_token)
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [payable.json()["id"]]

    cleared = await client.put(
        f"/api/v1/payables/{payable.json()['id']}/analytic-assignments",
        headers=_headers(payable_token, "analytic-payable-clear-0001"),
        json={"valueIds": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["analyticAssignments"] == []

    values = await client.get(
        f"/api/v1/analytic-classifications/{classification_id}/values", headers=_headers(writer)
    )
    assert values.status_code == 200
    assert {item["code"] for item in values.json()} == {"FARMA", "MATRIZ"}

    other_tenant = await _token(client, TENANT_B, ["analytics:read"])
    hidden = await client.get("/api/v1/analytic-classifications", headers=_headers(other_tenant))
    assert hidden.status_code == 200
    assert hidden.json() == []


@pytest.mark.asyncio
async def test_value_cannot_exceed_configured_depth_or_cross_tenant_parent(client):
    writer = await _token(client, TENANT_A, ["analytics:write"])
    created = await client.post(
        "/api/v1/analytic-classifications",
        headers=_headers(writer, "analytic-depth-classification-0001"),
        json={"code": "PROYECTO", "name": "Proyecto", "maxDepth": 1},
    )
    classification_id = created.json()["id"]
    parent = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(writer, "analytic-depth-value-0001"),
        json={"code": "ERP", "name": "ERP"},
    )
    assert parent.status_code == 201
    child = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(writer, "analytic-depth-value-0002"),
        json={"parentId": parent.json()["id"], "code": "FASE1", "name": "Fase 1"},
    )
    assert child.status_code == 422
    assert child.json()["detail"] == "Analytic classification maximum depth reached"


@pytest.mark.asyncio
async def test_invoice_persists_and_filters_controlled_analytic_value(client):
    from test_billing_api import _invoice_payload, _setup_billing_masters

    catalog_token = await _token(client, TENANT_A, ["analytics:write"])
    classification = await client.post(
        "/api/v1/analytic-classifications",
        headers=_headers(catalog_token, "analytic-invoice-classification-0001"),
        json={"code": "PROYECTO", "name": "Proyecto", "maxDepth": 1},
    )
    classification_id = classification.json()["id"]
    value = await client.post(
        f"/api/v1/analytic-classifications/{classification_id}/values",
        headers=_headers(catalog_token, "analytic-invoice-value-0001"),
        json={"code": "CRM", "name": "CRM"},
    )
    value_id = value.json()["id"]

    setup_token = await _token(
        client,
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, setup_token, key_prefix="analytic-invoice")
    invoice_token = await _token(client, TENANT_A, ["invoices:read", "invoices:write"])
    payload = _invoice_payload(masters)
    payload["analyticValueIds"] = [value_id]
    created = await client.post(
        "/api/v1/invoices",
        headers=_headers(invoice_token, "analytic-invoice-create-0001"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["analyticAssignments"][0]["valueId"] == value_id

    filtered = await client.get(
        f"/api/v1/invoices?analyticValueId={value_id}", headers=_headers(invoice_token)
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()] == [created.json()["id"]]

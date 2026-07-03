import uuid

from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.platform import AuditEvent, IdempotencyRecord, OutboxEvent

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


async def token_for(client, email: str, tenant_id: uuid.UUID, scopes=None) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": email,
            "tenantId": str(tenant_id),
            "scopes": scopes or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def test_context_and_scope_enforcement(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    response = await client.get("/api/v1/context", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["tenantId"] == str(TENANT_A)

    forbidden = await client.get("/api/v1/parties", headers=auth(token))
    assert forbidden.status_code == 403
    assert "insufficient_scope" in forbidden.headers["www-authenticate"]


async def test_tenant_isolation_and_composite_reference_checks(client):
    token_a = await token_for(client, "a@iaerp.local", TENANT_A)
    token_b = await token_for(client, "b@iaerp.local", TENANT_B)

    party_a = await client.post(
        "/api/v1/parties",
        headers=auth(token_a, "tenant-a-party-0001"),
        json={
            "name": "Cliente A",
            "identificationType": "RUC",
            "identificationNumber": "1790000000001",
            "roles": ["CUSTOMER"],
        },
    )
    party_b = await client.post(
        "/api/v1/parties",
        headers=auth(token_b, "tenant-b-party-0001"),
        json={
            "name": "Cliente B",
            "identificationType": "RUC",
            "identificationNumber": "1790000000002",
            "roles": ["CUSTOMER"],
        },
    )
    assert party_a.status_code == 201
    assert party_b.status_code == 201

    list_a = await client.get("/api/v1/parties", headers=auth(token_a))
    list_b = await client.get("/api/v1/parties", headers=auth(token_b))
    assert [item["name"] for item in list_a.json()] == ["Cliente A"]
    assert [item["name"] for item in list_b.json()] == ["Cliente B"]

    taxes_b = await client.get("/api/v1/tax-categories", headers=auth(token_b))
    foreign_tax_id = taxes_b.json()[0]["id"]
    cross_tenant_product = await client.post(
        "/api/v1/products",
        headers=auth(token_a, "tenant-a-cross-tax-0001"),
        json={
            "name": "Invalid",
            "code": "INVALID",
            "unitPrice": "10.000000",
            "taxCategoryId": foreign_tax_id,
        },
    )
    assert cross_tenant_product.status_code == 404


async def test_idempotency_audit_and_outbox_are_atomic(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A)
    headers = auth(token, "party-idempotency-0001")
    payload = {
        "name": "Cliente",
        "identificationType": "RUC",
        "identificationNumber": "1791234567001",
        "roles": ["CUSTOMER"],
    }

    first = await client.post("/api/v1/parties", headers=headers, json=payload)
    replay = await client.post("/api/v1/parties", headers=headers, json=payload)
    conflict = await client.post(
        "/api/v1/parties",
        headers=headers,
        json={**payload, "name": "Different"},
    )
    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json() == replay.json()
    assert conflict.status_code == 409

    async with SessionFactory() as session:
        events = list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.tenant_id == TENANT_A)
                    .order_by(AuditEvent.sequence)
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].sequence == 1
        assert events[0].previous_hash is None
        assert await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        ) == 1
        assert await session.scalar(
            select(func.count()).select_from(IdempotencyRecord)
        ) == 1


async def test_automation_settings_and_service_account(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A)
    settings_response = await client.put(
        "/api/v1/automation/settings",
        headers=auth(token, "automation-settings-0001"),
        json={"writesEnabled": True, "dailyAmountLimit": "500.00"},
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["writesEnabled"] is True

    account_response = await client.post(
        "/api/v1/service-accounts",
        headers=auth(token, "service-account-0001"),
        json={
            "name": "Collections Agent",
            "scopes": ["context:read", "parties:read"],
            "expiresAt": "2030-01-01T00:00:00Z",
        },
    )
    assert account_response.status_code == 201
    body = account_response.json()
    assert body["clientSecret"]
    assert body["account"]["scopes"] == ["context:read", "parties:read"]

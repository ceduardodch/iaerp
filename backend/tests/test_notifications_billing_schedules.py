"""Calendario de facturación por cliente vía API (F4 del plan de avisos).

``PartyBillingSchedule`` es el dato que le dice al aviso ``CLIENTE_FACTURAR``
cuándo tocarle a cada cliente (ver ``tests/test_notifications_catalog.py``
para el aviso en sí). Aquí se prueba el CRUD que lo administra desde
``/notifications/billing-schedules``.
"""

import uuid

from app.db.session import SessionFactory
from app.models.masters import Party

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


async def token_for(client, tenant_id: uuid.UUID, scopes: list[str]) -> str:
    email = "a@iaerp.local" if tenant_id == TENANT_A else "b@iaerp.local"
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["accessToken"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_customer(
    *,
    tenant_id: uuid.UUID = TENANT_A,
    name: str = "ACME S.A.",
    number: str = "0999999999001",
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        party = Party(
            tenant_id=tenant_id,
            name=name,
            identification_type="RUC",
            identification_number=number,
            roles=["CUSTOMER"],
        )
        session.add(party)
        await session.flush()
        return party.id


async def test_create_list_and_update_a_billing_schedule(client) -> None:
    party_id = await create_customer()
    token = await token_for(client, TENANT_A, ["notifications:read", "notifications:write"])

    create_response = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-create-0001"},
        json={
            "partyId": str(party_id),
            "dayOfMonth": 10,
            "frequency": "MONTHLY",
            "amountHint": "250.00",
            "notes": "Servicio mensual",
        },
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["partyName"] == "ACME S.A."
    assert created["dayOfMonth"] == 10
    assert created["amountHint"] == "250.00"
    assert created["active"] is True
    schedule_id = created["id"]

    list_response = await client.get(
        "/api/v1/notifications/billing-schedules",
        headers=auth(token),
        params={"partyId": str(party_id)},
    )
    assert list_response.status_code == 200, list_response.text
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["id"] == schedule_id

    active_filter = await client.get(
        "/api/v1/notifications/billing-schedules",
        headers=auth(token),
        params={"active": "true"},
    )
    assert len(active_filter.json()) == 1

    update_response = await client.put(
        f"/api/v1/notifications/billing-schedules/{schedule_id}",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-update-0001"},
        json={
            "partyId": str(party_id),
            "dayOfMonth": 15,
            "frequency": "MONTHLY",
            "amountHint": "300.00",
            "notes": "Cambio de fecha",
            "active": False,
        },
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["id"] == schedule_id
    assert updated["dayOfMonth"] == 15
    assert updated["amountHint"] == "300.00"
    assert updated["active"] is False

    inactive_filter = await client.get(
        "/api/v1/notifications/billing-schedules",
        headers=auth(token),
        params={"active": "false"},
    )
    assert len(inactive_filter.json()) == 1
    assert inactive_filter.json()[0]["id"] == schedule_id

    still_active_filter = await client.get(
        "/api/v1/notifications/billing-schedules",
        headers=auth(token),
        params={"active": "true"},
    )
    assert still_active_filter.json() == []


async def test_create_with_non_monthly_frequency_and_no_anchor_month_is_422(client) -> None:
    party_id = await create_customer()
    token = await token_for(client, TENANT_A, ["notifications:write"])

    response = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-422-0000001"},
        json={"partyId": str(party_id), "dayOfMonth": 5, "frequency": "QUARTERLY"},
    )
    assert response.status_code == 422, response.text
    assert "anchor_month" in str(response.json()["detail"])


async def test_create_with_a_party_from_another_tenant_or_missing_is_404(client) -> None:
    other_party_id = await create_customer(tenant_id=TENANT_B, number="0999999999002")
    token = await token_for(client, TENANT_A, ["notifications:write"])

    other_tenant_response = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-404-0000001"},
        json={"partyId": str(other_party_id), "dayOfMonth": 1},
    )
    assert other_tenant_response.status_code == 404, other_tenant_response.text

    missing_response = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-404-0000002"},
        json={"partyId": str(uuid.uuid4()), "dayOfMonth": 1},
    )
    assert missing_response.status_code == 404, missing_response.text


async def test_exact_duplicate_schedule_is_409(client) -> None:
    party_id = await create_customer()
    token = await token_for(client, TENANT_A, ["notifications:write"])
    payload = {"partyId": str(party_id), "dayOfMonth": 1, "frequency": "MONTHLY"}

    first = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-dup-0000001"},
        json=payload,
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token), "Idempotency-Key": "billing-schedule-dup-0000002"},
        json=payload,
    )
    assert second.status_code == 409, second.text


async def test_tenant_isolation_and_scopes(client) -> None:
    party_id = await create_customer()
    token_a = await token_for(client, TENANT_A, ["notifications:write"])

    create_response = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(token_a), "Idempotency-Key": "billing-schedule-iso-0000001"},
        json={"partyId": str(party_id), "dayOfMonth": 1},
    )
    assert create_response.status_code == 201, create_response.text
    schedule_id = create_response.json()["id"]

    token_b = await token_for(client, TENANT_B, ["notifications:read", "notifications:write"])

    list_b = await client.get("/api/v1/notifications/billing-schedules", headers=auth(token_b))
    assert list_b.status_code == 200, list_b.text
    assert list_b.json() == []

    update_b = await client.put(
        f"/api/v1/notifications/billing-schedules/{schedule_id}",
        headers={**auth(token_b), "Idempotency-Key": "billing-schedule-iso-0000002"},
        json={"partyId": str(party_id), "dayOfMonth": 2},
    )
    assert update_b.status_code == 404, update_b.text

    no_scope_token = await token_for(client, TENANT_A, ["invoices:read"])
    forbidden_get = await client.get(
        "/api/v1/notifications/billing-schedules", headers=auth(no_scope_token)
    )
    assert forbidden_get.status_code == 403, forbidden_get.text

    forbidden_post = await client.post(
        "/api/v1/notifications/billing-schedules",
        headers={**auth(no_scope_token), "Idempotency-Key": "billing-schedule-iso-0000003"},
        json={"partyId": str(party_id), "dayOfMonth": 3},
    )
    assert forbidden_post.status_code == 403, forbidden_post.text

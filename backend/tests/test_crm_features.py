import uuid
from datetime import date

from app.db.session import SessionFactory
from app.models.masters import Party

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
USER_A = uuid.UUID("22222222-2222-4222-8222-222222222222")


async def token_for(client, email: str, tenant_id: uuid.UUID, scopes: list[str]) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def test_lead_with_new_contact_has_title_summary_owner_and_customer_conversion(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write"],
    )
    response = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "crm-new-party-lead-0001"),
        json={
            "partyName": "Contacto CRM",
            "partyIdentificationType": "CEDULA",
            "partyIdentificationNumber": "1713209771",
            "partyEmail": "crm@example.com",
            "partyPhone": "+593999000111",
            "partyAddress": "Quito",
            "title": "Venta de servicios AWS",
            "source": "Referido",
            "hotness": "HOT",
            "estimatedValue": "1250.50",
            "expectedCloseDate": date.today().isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    lead = response.json()
    assert lead["title"] == "Venta de servicios AWS"
    assert lead["party"]["name"] == "Contacto CRM"
    assert lead["party"]["phone"] == "+593999000111"
    assert lead["owner"]["id"] == str(USER_A)
    assert lead["owner"]["displayName"] == "User A"

    listed = await client.get("/api/v1/crm/leads", headers=auth(token))
    assert listed.status_code == 200
    assert listed.json()[0]["party"]["email"] == "crm@example.com"

    won = await client.put(
        f"/api/v1/crm/leads/{lead['id']}/status",
        headers=auth(token, "crm-win-lead-key-0001"),
        json={"newStatus": "WON"},
    )
    assert won.status_code == 200, won.text
    assert won.json()["status"] == "WON"
    async with SessionFactory() as session:
        party = await session.get(Party, uuid.UUID(lead["partyId"]))
        assert party is not None
        assert party.roles == ["CUSTOMER"]


async def test_crm_and_integrations_require_their_declared_scopes(client):
    restricted = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    assert (await client.get("/api/v1/crm/leads", headers=auth(restricted))).status_code == 403
    assert (
        await client.get("/api/v1/crm/integrations", headers=auth(restricted))
    ).status_code == 403

    communications = await token_for(client, "a@iaerp.local", TENANT_A, ["communications:read"])
    status = await client.get("/api/v1/crm/integrations", headers=auth(communications))
    assert status.status_code == 200
    assert status.json()["googleConnected"] is False
    assert status.json()["whatsappConnected"] is False


async def test_invoice_preview_and_collection_policy_are_server_authoritative(client):
    invoice_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:read", "invoices:write"]
    )
    preview = await client.post(
        "/api/v1/invoices/preview",
        headers=auth(invoice_token),
        json={
            "issueDate": date.today().isoformat(),
            "lines": [
                {
                    "productId": None,
                    "description": "Consultoría",
                    "quantity": "2",
                    "unitPrice": "50.000000",
                    "discount": "10.00",
                    "taxCode": "4",
                }
            ],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["subtotal"] == "90.00"
    assert preview.json()["taxTotal"] == "13.50"
    assert preview.json()["total"] == "103.50"

    collection_token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["receivables:read", "receivables:notify"],
    )
    updated = await client.put(
        "/api/v1/receivables/collection-policy",
        headers=auth(collection_token, "collection-policy-save-0001"),
        json={
            "enabled": True,
            "offsetsDays": [-3, 0, 7],
            "channels": ["EMAIL", "WHATSAPP"],
            "sendHour": 10,
            "emailTemplateId": "payment_email",
            "whatsappTemplateId": "payment_whatsapp",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["offsetsDays"] == [-3, 0, 7]
    read = await client.get("/api/v1/receivables/collection-policy", headers=auth(collection_token))
    assert read.status_code == 200
    assert read.json()["channels"] == ["EMAIL", "WHATSAPP"]

    tenant_b = await token_for(client, "b@iaerp.local", TENANT_B, ["receivables:read"])
    isolated = await client.get("/api/v1/receivables/collection-policy", headers=auth(tenant_b))
    assert isolated.status_code == 200
    assert isolated.json()["enabled"] is False

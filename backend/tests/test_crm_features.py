import uuid
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory
from app.models.masters import Party
from app.services import crm_integrations

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


async def test_lead_with_new_contact_allows_missing_identification_for_prospect(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "parties:read"],
    )
    response = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "crm-prospect-without-id-0001"),
        json={
            "partyName": "Prospecto sin RUC",
            "partyEmail": "prospecto@example.com",
            "title": "Primera conversación",
        },
    )
    assert response.status_code == 201, response.text
    parties = await client.get("/api/v1/parties", headers=auth(token))
    assert parties.status_code == 200, parties.text
    party = next(item for item in parties.json() if item["name"] == "Prospecto sin RUC")
    assert party["identificationType"] == "FINAL_CONSUMER"
    assert party["identificationNumber"].startswith("lead-")


async def test_lead_with_new_contact_has_title_summary_owner_and_customer_conversion(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "parties:read"],
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

    parties = await client.get("/api/v1/parties", headers=auth(token))
    assert parties.status_code == 200, parties.text
    assert parties.json()[0]["roles"] == []

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


async def test_campaign_capture_keeps_attribution_consent_and_deduplicates(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "leads:capture"],
    )
    payload = {
        "source": "META_LEAD_AD",
        "sourceExternalId": "meta-form-response-001",
        "partyName": "Prospecto de campaña",
        "partyEmail": "campana@example.com",
        "partyPhone": "+593999000111",
        "title": "Demo ControlTotal",
        "campaignId": "52530432385016",
        "campaignName": "ControlTotal - Leads",
        "adId": "52530473326616",
        "utmSource": "meta",
        "utmMedium": "paid_social",
        "utmCampaign": "controltotal_leads",
        "utmContent": "dolor-operativo",
        "consentCapturedAt": datetime.now(UTC).isoformat(),
        "consentTextVersion": "privacy-v1",
    }
    rejected_variant = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-foreign-variant-0001"),
        json={**payload, "campaignVariantId": str(uuid.uuid4())},
    )
    assert rejected_variant.status_code == 422
    rejected_naive_consent = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-naive-consent-0001"),
        json={
            **payload,
            "sourceExternalId": "meta-form-response-naive-001",
            "consentCapturedAt": "2026-08-04T12:00:00",
        },
    )
    assert rejected_naive_consent.status_code == 422

    created = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-create-0001"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True
    assert body["lead"]["source"] == "META_LEAD_AD"
    assert body["lead"]["campaignId"] == "52530432385016"
    assert body["lead"]["consentTextVersion"] == "privacy-v1"
    assert body["lead"]["party"]["email"] == "campana@example.com"

    duplicate = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-create-0002"),
        json=payload,
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["created"] is False
    assert duplicate.json()["duplicateReason"] == "SOURCE_REFERENCE"
    assert duplicate.json()["lead"]["id"] == body["lead"]["id"]

    second_touch_payload = {
        **payload,
        "sourceExternalId": "meta-form-response-002",
        "campaignId": "second-campaign",
        "campaignName": "Segunda campaña",
    }
    second_touch = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-second-touch-0001"),
        json=second_touch_payload,
    )
    assert second_touch.status_code == 201, second_touch.text
    assert second_touch.json()["created"] is False
    assert second_touch.json()["duplicateReason"] == "CONTACT"
    repeated_touch = await client.post(
        "/api/v1/crm/leads/captures",
        headers=auth(token, "campaign-capture-second-touch-0002"),
        json=second_touch_payload,
    )
    assert repeated_touch.status_code == 201, repeated_touch.text
    assert repeated_touch.json()["duplicateReason"] == "SOURCE_REFERENCE"
    activities = await client.get(
        f"/api/v1/crm/leads/{body['lead']['id']}/activities",
        headers=auth(token),
    )
    assert activities.status_code == 200
    assert sum(item["subject"] == "Nueva respuesta de campaña" for item in activities.json()) == 1
    blocked_win = await client.put(
        f"/api/v1/crm/leads/{body['lead']['id']}/status",
        headers=auth(token, "campaign-capture-win-0001"),
        json={"newStatus": "WON"},
    )
    assert blocked_win.status_code == 422


async def test_campaign_capture_accepts_linkedin_and_tiktok_sources(client):
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "leads:capture"],
    )
    for index, source in enumerate(("LINKEDIN_LEAD_GEN", "TIKTOK_LEAD_GEN"), start=1):
        response = await client.post(
            "/api/v1/crm/leads/captures",
            headers=auth(token, f"campaign-multichannel-capture-{index:04d}"),
            json={
                "source": source,
                "sourceExternalId": f"provider-lead-{index}",
                "partyName": f"Prospecto multicanal {index}",
                "partyEmail": f"multicanal-{index}@example.com",
                "title": "Solicitud desde formulario social",
                "campaignId": f"provider-campaign-{index}",
                "campaignName": f"Campaña multicanal {index}",
                "adId": f"provider-ad-{index}",
                "utmSource": "linkedin" if source == "LINKEDIN_LEAD_GEN" else "tiktok",
                "utmMedium": "paid_social",
                "consentCapturedAt": datetime.now(UTC).isoformat(),
                "consentTextVersion": f"{source.lower()}:form-v1",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["created"] is True
        assert response.json()["lead"]["source"] == source
        assert response.json()["lead"]["status"] == "NEW"

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
    assert status.json()["whatsappCrmProvider"] == "META"
    assert status.json()["whatsappCollectionsProvider"] == "META"


async def test_whatsapp_routing_can_use_meta_and_evolution_per_operational_purpose(
    client, monkeypatch
):
    from app.services import crm_integrations

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload

        @property
        def is_error(self) -> bool:
            return self.status_code >= 400

        def json(self) -> dict[str, object]:
            return self._payload

    class FakeEvolutionClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs):
            if url.endswith("/instance/create"):
                return FakeResponse(201, {"instance": {"instanceName": "tenant-a"}})
            assert url.endswith("/webhook/set/tenant-a")
            return FakeResponse(200, {"webhook": {"enabled": True}})

        async def get(self, url: str, **_kwargs):
            assert url.endswith("/instance/connect/tenant-a")
            return FakeResponse(200, {"base64": "data:image/png;base64,qr-test"})

    monkeypatch.setattr(crm_integrations.settings, "EVOLUTION_API_BASE_URL", "https://evo.example")
    monkeypatch.setattr(
        crm_integrations.settings, "EVOLUTION_API_KEY", SecretStr("evolution-platform-key")
    )
    monkeypatch.setattr(crm_integrations.settings, "PUBLIC_API_URL", "https://api.example/api/v1")
    monkeypatch.setattr(
        crm_integrations.httpx, "AsyncClient", lambda **_kwargs: FakeEvolutionClient()
    )
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["communications:read", "communications:write"],
    )

    saved = await client.put(
        "/api/v1/crm/integrations/whatsapp/evolution",
        headers=auth(token),
        json={
            "instanceName": "tenant-a",
            "displayPhoneNumber": "+593999000111",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["connected"] is True
    assert saved.json()["qrCode"] == "data:image/png;base64,qr-test"
    assert saved.json()["qrExpiresInSeconds"] == 30
    assert saved.json()["webhookUrl"].startswith(
        "https://api.example/api/v1/crm/webhooks/whatsapp/evolution/"
    )
    webhook_path = urlsplit(saved.json()["webhookUrl"]).path
    webhook = await client.post(
        webhook_path,
        json={"event": "MESSAGES_UPSERT", "data": {"key": {"fromMe": True}}},
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json() == {"activitiesCreated": 0}
    rejected_webhook = await client.post(f"{webhook_path}-invalid", json={})
    assert rejected_webhook.status_code == 401

    routed = await client.put(
        "/api/v1/crm/integrations/whatsapp/routing",
        headers=auth(token),
        json={"crmProvider": "EVOLUTION", "collectionsProvider": "META"},
    )
    assert routed.status_code == 200, routed.text
    assert routed.json()["whatsappEvolutionConnected"] is True
    assert routed.json()["whatsappCrmProvider"] == "EVOLUTION"
    assert routed.json()["whatsappCollectionsProvider"] == "META"


async def test_invoice_preview_and_collection_policy_are_server_authoritative(client):
    invoice_token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:read", "invoices:write"]
    )
    preview = await client.post(
        "/api/v1/invoices/preview",
        headers=auth(invoice_token),
        json={
            # Fecha de hoy en la timezone FISCAL (America/Guayaquil), la misma
            # fuente que usa la validación del servidor. Con date.today() (UTC en
            # CI) el test flakeaba entre 00:00–05:00 UTC: en Guayaquil aún era el
            # día anterior, así que la fecha "de hoy en UTC" caía en el futuro.
            "issueDate": today_in_fiscal_timezone().isoformat(),
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


async def test_lead_activity_creation_returns_201_and_ignores_body_lead_id(client):
    """Regresion: el body incluye lead_id (schema) y el path tambien; el
    servicio debe usar el del path sin chocar (antes: TypeError -> 500)."""

    token = await token_for(client, "a@iaerp.local", TENANT_A, ["leads:read", "leads:write"])
    created = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "crm-activity-lead-0001"),
        json={
            "partyName": "Contacto Actividad",
            "partyIdentificationType": "CEDULA",
            "partyIdentificationNumber": "1713209772",
            "title": "Lead con actividades",
        },
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]

    activity = await client.post(
        f"/api/v1/crm/leads/{lead_id}/activities",
        headers=auth(token, "crm-activity-note-0001"),
        json={
            "leadId": lead_id,
            "activityType": "NOTE",
            "subject": "Primer contacto",
            "description": "Llamada inicial registrada desde el modal",
        },
    )
    assert activity.status_code == 201, activity.text
    assert activity.json()["subject"] == "Primer contacto"

    timeline = await client.get(f"/api/v1/crm/leads/{lead_id}/activities", headers=auth(token))
    assert timeline.status_code == 200
    assert [item["subject"] for item in timeline.json()] == ["Primer contacto"]


async def test_lead_email_schedules_follow_up_and_can_be_closed(client, monkeypatch):
    """Un envío sin seguimiento agendado se pierde: nadie vuelve al lead.

    Cubre el hueco que dejaba el modal del kanban, que solo registraba la
    actividad (``/activities``) en vez de despachar el correo (``/messages``).
    """
    sent: list[dict[str, str]] = []

    async def fake_send(session, context, *, recipient, subject, message, **kwargs):
        sent.append({"recipient": recipient, "subject": subject, "message": message})
        return "gmail-message-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", fake_send)

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:read", "leads:write", "communications:write"],
    )
    created = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token, "crm-followup-lead-0001"),
        json={
            "partyName": "Prospecto ISV",
            "partyIdentificationType": "RUC",
            "partyIdentificationNumber": "1791234567001",
            "partyEmail": "contacto@isv.example",
            "title": "Operación AWS gestionada",
        },
    )
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/crm/leads/{lead_id}/messages",
        headers=auth(token, "crm-followup-send-0001"),
        json={
            "channel": "EMAIL",
            "subject": "pregunta rápida sobre su AWS",
            "message": "¿Quién les lleva la operación de AWS hoy?",
            "followUpDays": 4,
        },
    )
    assert response.status_code == 201, response.text
    activity = response.json()
    # El correo salió de verdad, no solo se registró.
    assert sent == [
        {
            "recipient": "contacto@isv.example",
            "subject": "pregunta rápida sobre su AWS",
            "message": "¿Quién les lleva la operación de AWS hoy?",
        }
    ]
    assert activity["activityType"] == "EMAIL"
    assert activity["reminderCompleted"] is False
    reminder = datetime.fromisoformat(activity["reminderDate"])
    delta_days = (reminder - datetime.now(UTC)).total_seconds() / 86400
    assert 3.9 < delta_days < 4.1

    closed = await client.put(
        f"/api/v1/crm/leads/{lead_id}/activities/{activity['id']}/reminder",
        headers=auth(token, "crm-followup-close-0001"),
        json={"completed": True},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["reminderCompleted"] is True


async def test_lead_reminder_of_another_tenant_is_not_reachable(client, monkeypatch):
    """El activity_id ajeno no debe distinguirse de uno inexistente."""
    async def fake_send(session, context, *, recipient, subject, message, **kwargs):
        return "gmail-message-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", fake_send)

    token_a = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["leads:write", "communications:write"],
    )
    created = await client.post(
        "/api/v1/crm/leads/with-party",
        headers=auth(token_a, "crm-tenant-lead-0001"),
        json={
            "partyName": "Prospecto A",
            "partyIdentificationType": "RUC",
            "partyIdentificationNumber": "1791234567001",
            "partyEmail": "a@isv.example",
            "title": "Operación AWS gestionada",
        },
    )
    lead_id = created.json()["id"]
    message = await client.post(
        f"/api/v1/crm/leads/{lead_id}/messages",
        headers=auth(token_a, "crm-tenant-send-0001"),
        json={
            "channel": "EMAIL",
            "subject": "Hola",
            "message": "Texto",
            "followUpDays": 2,
        },
    )
    activity_id = message.json()["id"]

    token_b = await token_for(client, "b@iaerp.local", TENANT_B, ["leads:write"])
    intruso = await client.put(
        f"/api/v1/crm/leads/{lead_id}/activities/{activity_id}/reminder",
        headers=auth(token_b, "crm-tenant-close-0001"),
        json={"completed": True},
    )
    assert intruso.status_code == 404, intruso.text


async def test_lead_listing_pages_without_overlap_or_gaps(client):
    """El tablero pedía una sola página y el endpoint topaba en 100.

    Un pipeline mayor se veía truncado sin aviso, y el cargador de prospectos
    no podía deduplicar por RUC más allá de los 100 leads más recientes.
    """
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["leads:read", "leads:write"])
    creados: list[str] = []
    for indice in range(5):
        response = await client.post(
            "/api/v1/crm/leads/with-party",
            headers=auth(token, f"crm-paging-lead-{indice:04d}"),
            json={
                "partyName": f"Prospecto {indice}",
                "partyIdentificationType": "RUC",
                # RUC distinto por lead: Party es único por identificación.
                "partyIdentificationNumber": f"179123456{indice:04d}",
                "title": f"Operación AWS {indice}",
            },
        )
        assert response.status_code == 201, response.text
        creados.append(response.json()["id"])

    primera = await client.get("/api/v1/crm/leads?limit=2&offset=0", headers=auth(token))
    segunda = await client.get("/api/v1/crm/leads?limit=2&offset=2", headers=auth(token))
    tercera = await client.get("/api/v1/crm/leads?limit=2&offset=4", headers=auth(token))
    assert primera.status_code == 200, primera.text
    ids_paginados = [
        lead["id"] for página in (primera, segunda, tercera) for lead in página.json()
    ]
    # Sin solapamiento: los leads creados en la misma transacción comparten
    # ``created_at``, así que sin desempate por id las páginas se repetían.
    assert len(ids_paginados) == len(set(ids_paginados))
    assert set(creados).issubset(set(ids_paginados))

    completo = await client.get("/api/v1/crm/leads", headers=auth(token))
    assert [lead["id"] for lead in completo.json()][:5] == ids_paginados[:5]


async def test_lead_listing_rejects_limit_over_the_maximum(client):
    """Un ``limit`` enorme no debe poder pedir la tabla entera."""
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["leads:read"])
    excedido = await client.get("/api/v1/crm/leads?limit=100000", headers=auth(token))
    assert excedido.status_code == 422
    negativo = await client.get("/api/v1/crm/leads?offset=-1", headers=auth(token))
    assert negativo.status_code == 422

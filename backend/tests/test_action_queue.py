"""``GET /crm/action-queue`` -- bandeja única de candidatos a WhatsApp.

Agrega, solo lectura, dos flujos que ya existían por separado: recordatorios
de cobranza (``POST /receivables/{id}/reminders``) y mensajes de primer
contacto de leads (``POST /crm/leads/{id}/messages``). Este endpoint nunca
envía nada, así que estas pruebas verifican únicamente qué aparece, qué se
excluye y con qué datos, no el envío en sí (ya cubierto en
``test_receivables_reminder_template.py`` y ``test_crm_features.py``).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory
from app.models.crm import Lead, LeadActivity
from app.models.masters import Party
from app.models.receivables import CollectionReminder
from tests.conftest import TENANT_A, TENANT_B
from tests.test_billing_api import auth, token_for
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_receivable

_counter = iter(range(1, 100_000))


def _next_id_number() -> str:
    return f"17{next(_counter):09d}"[:13]


async def _create_party(
    session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    phone: str | None = "+593999000111",
    consent_opt_out: bool = False,
) -> Party:
    party = Party(
        tenant_id=tenant_id,
        name=name,
        identification_type="CEDULA",
        identification_number=_next_id_number(),
        roles=["CUSTOMER"],
        phone=phone,
        consent_opt_out=consent_opt_out,
    )
    session.add(party)
    await session.flush()
    return party


async def _create_overdue_receivable(
    session,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID,
    days_overdue: int = 10,
    amount: Decimal = Decimal("100.00"),
    collection_enabled: bool = True,
):
    invoice = await _create_authorized_invoice_stub(
        session, tenant_id=tenant_id, party_id=party_id, total=amount
    )
    due_date = today_in_fiscal_timezone() - timedelta(days=days_overdue)
    receivable, _ = await _create_receivable(
        session,
        tenant_id=tenant_id,
        party_id=party_id,
        sales_document_id=invoice.id,
        original_amount=amount,
        installment_amounts=[amount],
        due_date=due_date,
    )
    receivable.collection_enabled = collection_enabled
    await session.flush()
    return receivable


async def _create_lead(
    session,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID,
    title: str = "Interés en plan empresarial",
    status: str = "NEW",
) -> Lead:
    lead = Lead(tenant_id=tenant_id, party_id=party_id, title=title, status=status)
    session.add(lead)
    await session.flush()
    return lead


async def _create_lead_activity(
    session,
    *,
    tenant_id: uuid.UUID,
    lead_id: uuid.UUID,
    activity_type: str,
    created_at: datetime,
) -> LeadActivity:
    activity = LeadActivity(
        tenant_id=tenant_id,
        lead_id=lead_id,
        activity_type=activity_type,
        subject="Contacto de seguimiento",
        outcome="NEUTRAL",
        actor_id="tester@iaerp.local",
        created_at=created_at,
    )
    session.add(activity)
    await session.flush()
    return activity


async def _create_collection_reminder(
    session,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID,
    receivable_id: uuid.UUID,
    status: str,
    created_at: datetime,
) -> CollectionReminder:
    reminder = CollectionReminder(
        tenant_id=tenant_id,
        party_id=party_id,
        receivable_id=receivable_id,
        installment_id=None,
        channel="WHATSAPP",
        template_id="payment_reminder",
        recipient="+593999000111",
        status=status,
        created_at=created_at,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def _token(client, tenant_id: uuid.UUID = TENANT_A) -> str:
    email = "a@iaerp.local" if tenant_id == TENANT_A else "b@iaerp.local"
    return await token_for(client, email, tenant_id, scopes=["receivables:read", "leads:read"])


async def test_action_queue_lists_overdue_receivable_and_new_lead(client) -> None:
    async with SessionFactory() as session, session.begin():
        collection_party = await _create_party(
            session, tenant_id=TENANT_A, name="Cliente Moroso", phone="+593988000001"
        )
        receivable = await _create_overdue_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=collection_party.id,
            days_overdue=10,
            amount=Decimal("100.00"),
        )
        prospect_party = await _create_party(
            session, tenant_id=TENANT_A, name="Prospecto Nuevo", phone="+593988000002"
        )
        lead = await _create_lead(
            session,
            tenant_id=TENANT_A,
            party_id=prospect_party.id,
            title="Interés en plan empresarial",
        )

    token = await _token(client)
    response = await client.get("/api/v1/crm/action-queue", headers=auth(token))

    assert response.status_code == 200, response.text
    data = response.json()

    collections = {item["receivableId"]: item for item in data["collections"]}
    assert str(receivable.id) in collections
    collection_item = collections[str(receivable.id)]
    assert collection_item["partyName"] == "Cliente Moroso"
    assert collection_item["phone"] == "+593988000001"
    assert collection_item["openAmount"] == "100.00"
    assert collection_item["daysOverdue"] == 10
    assert collection_item["lastReminderAt"] is None
    assert "$100.00" in collection_item["suggestedMessage"]
    assert "10 día" in collection_item["suggestedMessage"]

    prospecting = {item["leadId"]: item for item in data["prospecting"]}
    assert str(lead.id) in prospecting
    prospect_item = prospecting[str(lead.id)]
    assert prospect_item["partyName"] == "Prospecto Nuevo"
    assert prospect_item["phone"] == "+593988000002"
    assert prospect_item["lastActivityAt"] is None
    assert "Interés en plan empresarial" in prospect_item["suggestedMessage"]


async def test_action_queue_excludes_receivable_with_recent_active_reminder(client) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session, session.begin():
        recent_party = await _create_party(
            session, tenant_id=TENANT_A, name="Cliente Con Recordatorio Reciente"
        )
        recent_receivable = await _create_overdue_receivable(
            session, tenant_id=TENANT_A, party_id=recent_party.id
        )
        await _create_collection_reminder(
            session,
            tenant_id=TENANT_A,
            party_id=recent_party.id,
            receivable_id=recent_receivable.id,
            status="SENT",
            created_at=now - timedelta(days=1),
        )

        old_party = await _create_party(
            session, tenant_id=TENANT_A, name="Cliente Con Recordatorio Antiguo"
        )
        old_receivable = await _create_overdue_receivable(
            session, tenant_id=TENANT_A, party_id=old_party.id
        )
        old_reminder_at = now - timedelta(days=10)
        await _create_collection_reminder(
            session,
            tenant_id=TENANT_A,
            party_id=old_party.id,
            receivable_id=old_receivable.id,
            status="SENT",
            created_at=old_reminder_at,
        )

    token = await _token(client)
    response = await client.get("/api/v1/crm/action-queue", headers=auth(token))

    assert response.status_code == 200, response.text
    collections = {item["receivableId"]: item for item in response.json()["collections"]}

    # Un recordatorio activo dentro de la ventana de enfriamiento (5 días por
    # defecto) excluye al candidato: ya se le mandó un mensaje hace poco.
    assert str(recent_receivable.id) not in collections

    # Un recordatorio fuera de la ventana no excluye, pero sí se refleja como
    # el último contacto conocido.
    assert str(old_receivable.id) in collections
    reported_at = collections[str(old_receivable.id)]["lastReminderAt"]
    assert datetime.fromisoformat(reported_at.replace("Z", "+00:00")) == old_reminder_at


async def test_action_queue_excludes_lead_with_recent_whatsapp_or_email_activity(client) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session, session.begin():
        whatsapp_party = await _create_party(session, tenant_id=TENANT_A, name="Lead Contactado")
        whatsapp_lead = await _create_lead(
            session, tenant_id=TENANT_A, party_id=whatsapp_party.id
        )
        await _create_lead_activity(
            session,
            tenant_id=TENANT_A,
            lead_id=whatsapp_lead.id,
            activity_type="WHATSAPP",
            created_at=now - timedelta(days=1),
        )

        note_party = await _create_party(session, tenant_id=TENANT_A, name="Lead Con Nota")
        note_lead = await _create_lead(session, tenant_id=TENANT_A, party_id=note_party.id)
        await _create_lead_activity(
            session,
            tenant_id=TENANT_A,
            lead_id=note_lead.id,
            activity_type="NOTE",
            created_at=now - timedelta(days=1),
        )

        stale_party = await _create_party(session, tenant_id=TENANT_A, name="Lead Contacto Viejo")
        stale_lead = await _create_lead(session, tenant_id=TENANT_A, party_id=stale_party.id)
        old_activity_at = now - timedelta(days=10)
        await _create_lead_activity(
            session,
            tenant_id=TENANT_A,
            lead_id=stale_lead.id,
            activity_type="EMAIL",
            created_at=old_activity_at,
        )

    token = await _token(client)
    response = await client.get("/api/v1/crm/action-queue", headers=auth(token))

    assert response.status_code == 200, response.text
    prospecting = {item["leadId"]: item for item in response.json()["prospecting"]}

    # WHATSAPP reciente excluye: ya se le escribió hace poco.
    assert str(whatsapp_lead.id) not in prospecting
    # NOTE no cuenta como contacto de WhatsApp/email, así que no excluye.
    assert str(note_lead.id) in prospecting
    # EMAIL fuera de la ventana no excluye, y se refleja como último contacto.
    assert str(stale_lead.id) in prospecting
    reported_at = prospecting[str(stale_lead.id)]["lastActivityAt"]
    assert datetime.fromisoformat(reported_at.replace("Z", "+00:00")) == old_activity_at


async def test_action_queue_excludes_opted_out_party_from_both_lists(client) -> None:
    async with SessionFactory() as session, session.begin():
        opted_out_collection_party = await _create_party(
            session, tenant_id=TENANT_A, name="Moroso Opt Out", consent_opt_out=True
        )
        opted_out_receivable = await _create_overdue_receivable(
            session, tenant_id=TENANT_A, party_id=opted_out_collection_party.id
        )

        opted_out_lead_party = await _create_party(
            session, tenant_id=TENANT_A, name="Prospecto Opt Out", consent_opt_out=True
        )
        opted_out_lead = await _create_lead(
            session, tenant_id=TENANT_A, party_id=opted_out_lead_party.id
        )

    token = await _token(client)
    response = await client.get("/api/v1/crm/action-queue", headers=auth(token))

    assert response.status_code == 200, response.text
    data = response.json()
    collection_ids = {item["receivableId"] for item in data["collections"]}
    lead_ids = {item["leadId"] for item in data["prospecting"]}

    assert str(opted_out_receivable.id) not in collection_ids
    assert str(opted_out_lead.id) not in lead_ids


async def test_action_queue_does_not_mix_candidates_across_tenants(client) -> None:
    async with SessionFactory() as session, session.begin():
        party_b = await _create_party(session, tenant_id=TENANT_B, name="Cliente Tenant B")
        receivable_b = await _create_overdue_receivable(
            session, tenant_id=TENANT_B, party_id=party_b.id
        )
        lead_party_b = await _create_party(session, tenant_id=TENANT_B, name="Lead Tenant B")
        lead_b = await _create_lead(session, tenant_id=TENANT_B, party_id=lead_party_b.id)

        party_a = await _create_party(session, tenant_id=TENANT_A, name="Cliente Tenant A")
        receivable_a = await _create_overdue_receivable(
            session, tenant_id=TENANT_A, party_id=party_a.id
        )
        lead_party_a = await _create_party(session, tenant_id=TENANT_A, name="Lead Tenant A")
        lead_a = await _create_lead(session, tenant_id=TENANT_A, party_id=lead_party_a.id)

    token_a = await _token(client, TENANT_A)
    response_a = await client.get("/api/v1/crm/action-queue", headers=auth(token_a))
    assert response_a.status_code == 200, response_a.text
    data_a = response_a.json()
    assert {item["receivableId"] for item in data_a["collections"]} == {str(receivable_a.id)}
    assert {item["leadId"] for item in data_a["prospecting"]} == {str(lead_a.id)}

    token_b = await _token(client, TENANT_B)
    response_b = await client.get("/api/v1/crm/action-queue", headers=auth(token_b))
    assert response_b.status_code == 200, response_b.text
    data_b = response_b.json()
    assert {item["receivableId"] for item in data_b["collections"]} == {str(receivable_b.id)}
    assert {item["leadId"] for item in data_b["prospecting"]} == {str(lead_b.id)}


async def test_action_queue_requires_both_receivables_and_leads_read_scopes(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, scopes=["receivables:read"])
    response = await client.get("/api/v1/crm/action-queue", headers=auth(token))
    assert response.status_code == 403

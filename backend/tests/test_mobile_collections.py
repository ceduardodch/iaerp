"""Native collection workflow with synthetic invoices and an in-memory mailbox."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.core.timezones import FISCAL_TIMEZONE, today_in_fiscal_timezone
from app.db.session import SessionFactory, engine
from app.models.billing import SalesDocument, SalesDocumentInstallment
from app.models.masters import Party
from app.models.platform import AuditEvent
from app.models.receivables import CollectionPolicy, CollectionReminder, Movement, Receivable
from app.schemas.receivables import ReminderInput
from app.services import crm_integrations, receivables
from app.workers.collections import dispatch_due_reminders_once, handle_collection_reminder_due
from app.workers.mobile_collections import deliver
from app.workers.outbox import OutboxMessage
from tests.test_billing_api import auth
from tests.test_ios_permissions import TENANT_A, claims, membership, oidc_signer
from tests.test_receivables_reminder_template import _context, _seed_receivable_with_policy
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_receivable

ROOT = "/api/v1/collections/accounts"


@pytest_asyncio.fixture
async def case(client, monkeypatch):
    account_id = await _seed_receivable_with_policy(
        payment_instructions="Banco de prueba, cuenta DEMO"
    )
    signer = oidc_signer(monkeypatch)
    token = signer(claims(scope="receivables:read collections:notify collections:terms"))
    detail = await client.get(f"{ROOT}/{account_id}", headers=auth(token))
    assert detail.status_code == 200, detail.text
    view = detail.json()
    body = {
        "expectedRecipient": view["email"],
        "expectedOpenAmount": view["openAmount"],
        "expectedDueDate": view["dueDate"],
    }
    return account_id, f"{ROOT}/{account_id}", token, view, body


def keyed(token):
    return auth(token, str(uuid.uuid4()))


async def get_row(account_id):
    async with SessionFactory() as session:
        return (
            await session.scalars(
                select(CollectionReminder).where(
                    CollectionReminder.receivable_id == account_id,
                    CollectionReminder.native_confirmation.is_not(None),
                )
            )
        ).one()


async def test_one_recipient_confirmation_and_stable_receipt(client, case, monkeypatch):
    rid, url, token, view, body = case
    assert (await client.get(ROOT, headers=auth(token))).json() == [view]
    assert view["customerName"] and Decimal(view["openAmount"]) == Decimal("359.24")
    assert len(view["installments"]) == 1 and view["installments"][0]["dueDate"] == view["dueDate"]
    for changed in [
        {"expectedRecipient": "other@example.org"},
        {"expectedOpenAmount": "0.01"},
        {"expectedDueDate": "2030-01-01"},
    ]:
        assert (
            await client.post(url + "/reminder", headers=keyed(token), json=body | changed)
        ).status_code == 409
    async with SessionFactory() as s, s.begin():
        receivable = await s.get(Receivable, rid)
        s.add(
            CollectionReminder(
                tenant_id=TENANT_A,
                party_id=receivable.party_id,
                receivable_id=rid,
                channel="EMAIL",
                status="PENDING",
                recipient=body["expectedRecipient"],
                template_id="future",
                scheduled_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
    key = keyed(token)
    requested = await client.post(url + "/reminder", headers=key, json=body)
    assert requested.status_code == 200, requested.text
    assert requested.json()["lastReminderStatus"] == "PENDING"
    assert (
        await client.post(url + "/reminder", headers=keyed(token), json=body)
    ).status_code == 409
    assert await dispatch_due_reminders_once() == 0
    mails = []

    async def fake(_session, ctx, **mail):
        mails.append(mail)
        return "captured-1"

    monkeypatch.setattr(crm_integrations, "send_google_email", fake)
    row = await get_row(rid)
    assert await deliver(TENANT_A, row.id)
    assert not await deliver(TENANT_A, row.id)
    assert len(mails) == 1 and mails[0]["recipient"] == view["email"]
    assert "359.24" in mails[0]["message"] and "Banco de prueba" in mails[0]["html_message"]
    assert (await client.get(url, headers=auth(token))).json()["lastReminderStatus"] == "SENT"
    async with SessionFactory() as s, s.begin():
        receivable = await s.get(Receivable, rid)
        receivable.status = "PAID"
    replay = await client.post(url + "/reminder", headers=key, json=body)
    assert replay.status_code == 200 and replay.json()["lastReminderStatus"] == "SENT"


async def test_timeout_reconciles_without_a_second_send(client, case, monkeypatch):
    rid, url, token, _, body = case
    transmitted = []

    async def timeout(*args, **kwargs):
        transmitted.append(kwargs)
        raise httpx.ReadTimeout("prueba")

    async def lookup(s, ctx, reference):
        assert reference == transmitted[0]["provider_reference"]
        return "captured-after-timeout"

    monkeypatch.setattr(crm_integrations, "send_google_email", timeout)
    monkeypatch.setattr(crm_integrations, "find_sent_reference", lookup)
    assert (
        await client.post(url + "/reminder", headers=keyed(token), json=body)
    ).status_code == 200
    row = await get_row(rid)
    with pytest.raises(httpx.ReadTimeout):
        await deliver(TENANT_A, row.id)
    assert (await client.get(url, headers=auth(token))).json()["lastReminderStatus"] == "UNCERTAIN"
    assert (
        await client.post(url + "/reminder", headers=keyed(token), json=body)
    ).status_code == 409
    assert await dispatch_due_reminders_once() == 0
    assert await deliver(TENANT_A, row.id)
    assert (
        len(transmitted) == 1
        and (await get_row(rid)).provider_message_id == "captured-after-timeout"
    )


@pytest.mark.parametrize(
    "change", ["promise", "revoke", "email", "paid", "void", "pause", "optout"]
)
async def test_worker_rechecks_before_transport(client, case, monkeypatch, change):
    rid, url, token, _, body = case
    assert (
        await client.post(url + "/reminder", headers=keyed(token), json=body)
    ).status_code == 200
    if change == "revoke":
        await membership(TENANT_A, ["viewer"])
    async with SessionFactory() as s, s.begin():
        r = await s.get(Receivable, rid)
        party = await s.get(Party, r.party_id)
        if change == "promise":
            r.promised_date = today_in_fiscal_timezone()
        if change == "email":
            party.email = "changed@example.org"
        if change == "paid":
            r.status = "PAID"
        if change == "void":
            (await s.get(SalesDocument, r.sales_document_id)).status = "VOIDED"
        if change == "pause":
            (await s.get(CollectionPolicy, TENANT_A)).enabled = False
        if change == "optout":
            party.consent_opt_out = True

    async def unexpected(*args, **kwargs):
        pytest.fail("No se permite transmitir")

    monkeypatch.setattr(crm_integrations, "send_google_email", unexpected)
    assert not await deliver(TENANT_A, (await get_row(rid)).id)
    assert (await get_row(rid)).status == "SKIPPED"


async def test_enable_account_and_promise_pause_all_paths(client, case):
    rid, url, token, view, body = case
    today = today_in_fiscal_timezone()
    async with SessionFactory() as s, s.begin():
        r = await s.get(Receivable, rid)
        r.collection_enabled = False
        rem = CollectionReminder(
            tenant_id=TENANT_A,
            party_id=r.party_id,
            receivable_id=r.id,
            channel="EMAIL",
            status="PROCESSING",
            recipient=view["email"],
            template_id="auto",
            scheduled_at=datetime.now(UTC) - timedelta(hours=1),
        )
        s.add(rem)
        await s.flush()
        reminder_id = rem.id
    assert (await client.get(url, headers=auth(token))).json()["canEnableReminders"] is True
    assert (await client.put(url + "/enable-reminders", json={}, headers=keyed(token))).json()[
        "collectionEnabled"
    ] is True
    updates = {"promisedDate": str(today), "previousPromisedDate": None}
    changed = await client.put(url + "/promise", json=updates, headers=keyed(token))
    assert changed.status_code == 200 and changed.json()["dueDate"] == view["dueDate"]
    assert (
        await client.put(url + "/promise", json=updates, headers=keyed(token))
    ).status_code == 409
    request = await client.post(url + "/reminder", headers=keyed(token), json=body)
    assert request.status_code == 409 and "prometida" in request.text
    async with SessionFactory() as s, s.begin():
        with pytest.raises(HTTPException) as exc:
            await receivables.send_real_reminder(
                s, _context(), receivable_id=rid, reminder=ReminderInput(channel="EMAIL")
            )
        assert exc.value.status_code == 409
        msg = OutboxMessage(
            uuid.uuid4(),
            TENANT_A,
            "collection.reminder.due",
            "collection_reminder",
            str(reminder_id),
            {},
            "test",
            1,
        )
        await handle_collection_reminder_due(s, msg)
        assert (await s.get(CollectionReminder, reminder_id)).status == "SKIPPED"
    cleared = await client.put(
        url + "/promise",
        json={"promisedDate": None, "previousPromisedDate": str(today)},
        headers=keyed(token),
    )
    assert cleared.json()["promisedDate"] is None and cleared.json()["dueDate"] == view["dueDate"]


async def test_selected_installment_earlier_later_and_stale_plan(client, case):
    _, _, token, _, _ = case
    today = today_in_fiscal_timezone()
    async with SessionFactory() as s, s.begin():
        party = (await s.scalars(select(Party).where(Party.tenant_id == TENANT_A))).one()
        doc = await _create_authorized_invoice_stub(
            s, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        r, parts = await _create_receivable(
            s,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=doc.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("30.00"), Decimal("70.00")],
            due_date=today + timedelta(days=15),
        )
        for p in parts:
            s.add(
                SalesDocumentInstallment(
                    tenant_id=TENANT_A,
                    sales_document_id=doc.id,
                    sequence=p.sequence,
                    amount=p.amount,
                    due_date=p.due_date,
                )
            )
        old = parts[1].due_date
        unchanged = parts[0].due_date
        target = parts[1].id
        settled = parts[0].id
        s.add(
            CollectionReminder(
                tenant_id=TENANT_A,
                party_id=party.id,
                receivable_id=r.id,
                installment_id=target,
                channel="EMAIL",
                status="PENDING",
                recipient=party.email,
                template_id="future",
                scheduled_at=datetime.combine(old, datetime.min.time(), tzinfo=UTC),
            )
        )
        url = f"{ROOT}/{r.id}/due-date"
    data = {
        "previousDueDate": str(old),
        "dueDate": str(old + timedelta(days=7)),
        "reason": "Acuerdo de prueba",
    }
    assert (await client.put(url, json=data, headers=keyed(token))).status_code == 422
    assert (
        await client.put(
            url, json=data | {"installmentId": str(uuid.uuid4())}, headers=keyed(token)
        )
    ).status_code == 409
    data["installmentId"] = str(target)
    first = await client.put(url, json=data, headers=keyed(token))
    assert first.status_code == 200, first.text
    assert [p["dueDate"] for p in first.json()["installments"]] == [str(unchanged), data["dueDate"]]
    assert (await client.put(url, json=data, headers=keyed(token))).status_code == 409
    data.update(previousDueDate=data["dueDate"], dueDate=str(old - timedelta(days=3)))
    assert (await client.put(url, json=data, headers=keyed(token))).status_code == 200
    async with SessionFactory() as s:
        plan = (
            await s.scalars(
                select(SalesDocumentInstallment)
                .where(SalesDocumentInstallment.sales_document_id == doc.id)
                .order_by(SalesDocumentInstallment.sequence)
            )
        ).all()
        assert [p.due_date for p in plan] == [unchanged, old - timedelta(days=3)]
        auto = (
            await s.scalars(
                select(CollectionReminder).where(CollectionReminder.installment_id == target)
            )
        ).one()
        assert str(auto.scheduled_at.date()) == data["dueDate"]
        events = (
            await s.scalars(
                select(AuditEvent).where(AuditEvent.action == "receivable.due_date_corrected")
            )
        ).all()
        assert len(events) == 2 and all(e.details["installment_id"] == str(target) for e in events)

    async with SessionFactory() as s, s.begin():
        s.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=r.id,
                installment_id=settled,
                movement_type="PAYMENT",
                amount=Decimal("30.00"),
                actor_id="demo",
            )
        )
    response = await client.put(
        url,
        json=data | {"installmentId": str(settled), "previousDueDate": str(unchanged)},
        headers=keyed(token),
    )
    assert response.status_code == 409 and "cuota pendiente" in response.text


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Requires PostgreSQL row locks")
async def test_concurrent_individual_reminders_reserve_a_single_contact(client, case, monkeypatch):
    rid, url, token, _, body = case
    responses = await asyncio.gather(
        *(client.post(url + "/reminder", headers=keyed(token), json=body) for _ in range(2))
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    row = await get_row(rid)
    captures = []

    async def accept(*args, **kwargs):
        captures.append(kwargs)
        return "concurrent-capture"

    async def reconcile(*args):
        return "concurrent-capture" if captures else None

    monkeypatch.setattr(crm_integrations, "send_google_email", accept)
    monkeypatch.setattr(crm_integrations, "find_sent_reference", reconcile)
    outcomes = await asyncio.gather(
        deliver(TENANT_A, row.id), deliver(TENANT_A, row.id), return_exceptions=True
    )
    assert True in outcomes
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            assert isinstance(outcome, RuntimeError) and "aún no confirma" in str(outcome)
    assert len(captures) == 1 and (await get_row(rid)).status == "SENT"


async def test_terminal_rejection_is_not_retried_in_background(client, case, monkeypatch):
    rid, url, token, _, body = case
    captures = []

    async def reject(*args, **kwargs):
        captures.append(kwargs)
        raise crm_integrations.GoogleSendRejected(502, "Rechazo de prueba")

    monkeypatch.setattr(crm_integrations, "send_google_email", reject)
    assert (
        await client.post(url + "/reminder", headers=keyed(token), json=body)
    ).status_code == 200
    row = await get_row(rid)
    assert not await deliver(TENANT_A, row.id)
    assert not await deliver(TENANT_A, row.id)
    assert await dispatch_due_reminders_once() == 0
    assert (await client.get(url, headers=auth(token))).json()["lastReminderStatus"] == "FAILED"
    assert len(captures) == 1


async def test_new_due_time_prevents_dispatch_of_an_old_event(case, monkeypatch):
    rid, _, _, view, _ = case
    now = datetime.now(UTC)
    due = now + timedelta(hours=2)
    async with SessionFactory() as session, session.begin():
        r = await session.get(Receivable, rid)
        row = CollectionReminder(
            tenant_id=TENANT_A,
            party_id=r.party_id,
            receivable_id=r.id,
            channel="EMAIL",
            status="PENDING",
            recipient=view["email"],
            template_id="test",
            scheduled_at=due,
        )
        session.add(row)
        await session.flush()
        reminder_id = row.id

    msg = OutboxMessage(
        uuid.uuid4(),
        TENANT_A,
        "collection.reminder.due",
        "collection_reminder",
        str(reminder_id),
        {},
        "test",
        1,
    )
    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(session, msg, now=now)
        assert (await session.get(CollectionReminder, reminder_id)).status == "PENDING"
        (await session.get(Receivable, rid)).promised_date = due.astimezone(FISCAL_TIMEZONE).date()
    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(session, msg, now=due)
        assert (await session.get(CollectionReminder, reminder_id)).status == "SKIPPED"

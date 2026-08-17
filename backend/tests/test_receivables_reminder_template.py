"""El correo de cobro manual usa la plantilla configurada del tenant.

Antes el botón "Enviar recordatorio" mandaba un texto fijo ("Recordatorio de
pago") sin los datos bancarios ni la invitación a acordar un plan de pago,
mientras el recordatorio automático sí usaba la plantilla. El cliente recibía
dos mensajes distintos según quién lo disparara. Estas pruebas fijan que ambos
caminos rendericen la MISMA plantilla.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.billing import SalesDocument
from app.models.masters import Party
from app.models.receivables import (
    CollectionPolicy,
    CollectionReminder,
    Movement,
    Receivable,
    ReceivableInstallment,
)
from app.schemas.receivables import CollectionContactCreate, ReminderInput
from app.services import crm_integrations, receivables
from app.workers.collections import handle_collection_reminder_due
from app.workers.outbox import OutboxMessage
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_receivable

BANK_BLOCK = "PRODUBANCO\nBTOB SAS\nCUENTA CORRIENTE\n27059028731\ncontabilidad@b2b.com.ec"


def _context() -> AuthContext:
    return AuthContext(
        actor_id="tester@iaerp.local",
        actor_type="USER",
        tenant_id=TENANT_A,
        roles=frozenset(),
        scopes=frozenset({"receivables:notify"}),
        token_id="test-token",
    )


@pytest.fixture
def sent_emails(monkeypatch) -> list[dict[str, str]]:
    """Captura el correo en vez de llamar a Gmail."""
    captured: list[dict[str, str]] = []

    async def fake_send(session, context, *, recipient, subject, message, html_message=None):
        captured.append(
            {
                "recipient": recipient,
                "subject": subject,
                "message": message,
                "html_message": html_message or "",
            }
        )
        return "fake-message-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", fake_send)
    return captured


async def _seed_receivable_with_policy(*, payment_instructions: str = BANK_BLOCK) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        party = Party(
            tenant_id=TENANT_A,
            name="Cliente Cobranza",
            identification_type="RUC",
            identification_number="1790000001001",
            roles=["CUSTOMER"],
            email="cliente@ejemplo.com",
        )
        session.add(party)
        await session.flush()

        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("359.24")
        )
        receivable, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("359.24"),
            installment_amounts=[Decimal("359.24")],
            due_date=date(2026, 7, 1),
        )
        # Estos casos prueban el contenido del mensaje, así que activan de
        # forma explícita la nueva decisión por factura.
        receivable.collection_enabled = True
        session.add(
            CollectionPolicy(
                tenant_id=TENANT_A,
                enabled=True,
                email_subject="Saldo pendiente - {{empresa}}",
                payment_instructions=payment_instructions,
            )
        )
        return receivable.id


async def test_collection_permission_can_be_enabled_after_invoice_authorization() -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        entity = await session.get(Receivable, receivable_id)
        assert entity is not None
        entity.collection_enabled = False
        document = await session.scalar(
            select(SalesDocument).where(SalesDocument.id == entity.sales_document_id)
        )
        assert document is not None
        document.collection_enabled = False

        summary = await receivables.update_receivable_collection_policy(
            session,
            _context(),
            receivable_id=receivable_id,
            enabled=True,
        )

        assert summary.collection_enabled is True
        assert entity.collection_enabled is True
        assert document.collection_enabled is True


async def test_collection_permission_endpoint_is_idempotent_for_issued_invoice(client) -> None:
    receivable_id = await _seed_receivable_with_policy()
    async with SessionFactory() as session, session.begin():
        entity = await session.get(Receivable, receivable_id)
        assert entity is not None
        entity.collection_enabled = False

    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        scopes=["receivables:notify"],
    )
    headers = auth(token, "enable-issued-collection-0001")
    response = await client.put(
        f"/api/v1/receivables/{receivable_id}/collection-policy",
        headers=headers,
        json={"enabled": True},
    )
    replay = await client.put(
        f"/api/v1/receivables/{receivable_id}/collection-policy",
        headers=headers,
        json={"enabled": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["collectionEnabled"] is True
    assert replay.status_code == 200
    assert replay.json() == response.json()


async def test_manual_email_uses_the_tenant_subject_and_bank_details(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )

    assert len(sent_emails) == 1
    email = sent_emails[0]
    assert email["recipient"] == "cliente@ejemplo.com"
    # El asunto sale de la plantilla del tenant, no del texto fijo anterior.
    assert email["subject"] == "Saldo pendiente - Tenant A"
    # Los datos bancarios viajan en el correo manual, igual que en el programado.
    assert "27059028731" in email["message"]
    assert "PRODUBANCO" in email["message"]


async def test_manual_email_invites_to_agree_a_payment_plan(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )

    body = sent_emails[0]["message"]
    # El cuerpo por defecto abre la puerta al acuerdo de pago, no solo reclama.
    assert "plan de pagos" in body
    # Y muestra el saldo real de la cuenta, no un texto genérico.
    assert "$359.24" in body


async def test_custom_message_keeps_the_balance_and_bank_details(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(
                channel="EMAIL", message="Hola {{cliente}}, coordinamos por teléfono."
            ),
        )

    body = sent_emails[0]["message"]
    assert "Hola Cliente Cobranza, coordinamos por teléfono." in body
    # Personalizar el cuerpo no puede borrar el saldo ni la cuenta bancaria.
    assert "$359.24" in body
    assert "27059028731" in body


async def test_email_is_sent_as_html_with_the_payment_table(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )

    html_message = sent_emails[0]["html_message"]
    assert "Saldo pendiente" in html_message
    assert "Datos para pago" in html_message
    # El bloque bancario multilinea no puede colapsar en una sola línea.
    assert "PRODUBANCO<br>BTOB SAS" in html_message


async def test_tenant_without_bank_details_does_not_invent_an_account(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy(payment_instructions="")

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )

    body = sent_emails[0]["message"]
    assert "Consulte con nuestro equipo." in body
    assert "PRODUBANCO" not in body


async def test_scheduled_manual_email_uses_receivable_context(
    monkeypatch, sent_emails
) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async def fake_google_integration(session, tenant_id):
        return SimpleNamespace(user_id=uuid.uuid4())

    monkeypatch.setattr(
        crm_integrations, "google_integration_for_tenant", fake_google_integration
    )
    async with SessionFactory() as session, session.begin():
        reminder = await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(
                channel="EMAIL", scheduled_at=datetime.now(UTC) + timedelta(hours=1)
            ),
        )
        assert reminder.installment_id is None
        reminder_id = reminder.id

    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(
            session,
            OutboxMessage(
                event_id=uuid.uuid4(),
                tenant_id=TENANT_A,
                event_type="collection.reminder.due",
                aggregate_type="collection_reminder",
                aggregate_id=str(reminder_id),
                payload={},
                correlation_id="scheduled-manual-test",
                attempts=1,
            ),
        )

    async with SessionFactory() as session:
        stored = await session.get(CollectionReminder, reminder_id)
        assert stored is not None
        assert stored.status == "SENT"
    assert len(sent_emails) == 1
    assert "$359.24" in sent_emails[0]["message"]


async def test_scheduled_manual_email_uses_oldest_open_installment(
    monkeypatch, sent_emails
) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async def fake_google_integration(session, tenant_id):
        return SimpleNamespace(user_id=uuid.uuid4())

    monkeypatch.setattr(
        crm_integrations, "google_integration_for_tenant", fake_google_integration
    )
    async with SessionFactory() as session, session.begin():
        first = await session.scalar(
            select(ReceivableInstallment).where(
                ReceivableInstallment.receivable_id == receivable_id
            )
        )
        assert first is not None
        first.amount = Decimal("100.00")
        first.due_date = date(2026, 6, 1)
        second = ReceivableInstallment(
            tenant_id=TENANT_A,
            receivable_id=receivable_id,
            sequence=2,
            due_date=date(2026, 8, 1),
            amount=Decimal("259.24"),
        )
        session.add(second)
        await session.flush()
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable_id,
                installment_id=first.id,
                movement_type="PAYMENT",
                amount=Decimal("100.00"),
                effective_date=date(2026, 6, 1),
                actor_id="tester@iaerp.local",
            )
        )
        reminder = await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(
                channel="EMAIL", scheduled_at=datetime.now(UTC) + timedelta(hours=1)
            ),
        )
        reminder_id = reminder.id

    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(
            session,
            OutboxMessage(
                event_id=uuid.uuid4(),
                tenant_id=TENANT_A,
                event_type="collection.reminder.due",
                aggregate_type="collection_reminder",
                aggregate_id=str(reminder_id),
                payload={},
                correlation_id="scheduled-open-installment-test",
                attempts=1,
            ),
        )

    assert len(sent_emails) == 1
    assert "$259.24" in sent_emails[0]["message"]
    assert "01/08/2026" in sent_emails[0]["message"]
    assert "01/06/2026" not in sent_emails[0]["message"]


@pytest.mark.parametrize("channel", ["EMAIL", "WHATSAPP"])
async def test_scheduled_message_is_skipped_when_account_was_paid(
    monkeypatch, sent_emails, channel
) -> None:
    receivable_id = await _seed_receivable_with_policy()
    sent_whatsapp: list[str] = []

    async def fake_google_integration(session, tenant_id):
        return SimpleNamespace(user_id=uuid.uuid4())

    async def fake_send_whatsapp(session, context, **kwargs):
        sent_whatsapp.append(kwargs["recipient"])
        return "fake-whatsapp-id"

    monkeypatch.setattr(
        crm_integrations, "google_integration_for_tenant", fake_google_integration
    )
    monkeypatch.setattr(crm_integrations, "send_whatsapp_message", fake_send_whatsapp)
    async with SessionFactory() as session, session.begin():
        installment = await session.scalar(
            select(ReceivableInstallment).where(
                ReceivableInstallment.receivable_id == receivable_id
            )
        )
        assert installment is not None
        reminder = await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(
                channel="EMAIL", scheduled_at=datetime.now(UTC) + timedelta(hours=1)
            ),
        )
        reminder.channel = channel
        if channel == "WHATSAPP":
            reminder.recipient = "+593999999999"
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable_id,
                installment_id=installment.id,
                movement_type="PAYMENT",
                amount=installment.amount,
                effective_date=date(2026, 7, 1),
                actor_id="tester@iaerp.local",
            )
        )
        reminder_id = reminder.id

    async with SessionFactory() as session, session.begin():
        await handle_collection_reminder_due(
            session,
            OutboxMessage(
                event_id=uuid.uuid4(),
                tenant_id=TENANT_A,
                event_type="collection.reminder.due",
                aggregate_type="collection_reminder",
                aggregate_id=str(reminder_id),
                payload={},
                correlation_id="scheduled-paid-account-test",
                attempts=1,
            ),
        )

    async with SessionFactory() as session:
        stored = await session.get(CollectionReminder, reminder_id)
        assert stored is not None
        assert stored.status == "SKIPPED"
        assert stored.error_message == "Receivable has no open balance"
    assert sent_emails == []
    assert sent_whatsapp == []


async def test_scheduled_manual_email_rejects_unpersisted_custom_body(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        with pytest.raises(HTTPException, match="plantilla general") as error:
            await receivables.send_real_reminder(
                session,
                _context(),
                receivable_id=receivable_id,
                reminder=ReminderInput(
                    channel="EMAIL",
                    scheduled_at=datetime.now(UTC) + timedelta(hours=1),
                    message="Texto que no debe perderse silenciosamente",
                ),
            )

    assert error.value.status_code == 422
    assert sent_emails == []


async def test_collection_history_keeps_sent_message_and_human_contact(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        reminder = await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )
        assert reminder.provider_message_id == "fake-message-id"
        assert reminder.delivery_status == "SENT"
        contact = await receivables.record_collection_contact(
            session,
            _context(),
            receivable_id=receivable_id,
            data=CollectionContactCreate(
                channel="CALL", outcome="PROMISE_TO_PAY", note="Confirma pago el viernes."
            ),
        )
        assert contact.actor_id == "tester@iaerp.local"
        history = await receivables.list_collection_history(
            session, _context(), receivable_id=receivable_id
        )

    assert {entry.kind for entry in history} == {"REMINDER", "CONTACT"}
    assert next(entry for entry in history if entry.kind == "REMINDER").delivery_status == "SENT"
    assert next(entry for entry in history if entry.kind == "CONTACT").outcome == "PROMISE_TO_PAY"


async def test_same_manual_message_requires_a_reason_to_resend(sent_emails) -> None:
    receivable_id = await _seed_receivable_with_policy()

    async with SessionFactory() as session, session.begin():
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL"),
        )
        with pytest.raises(HTTPException, match="already sent") as error:
            await receivables.send_real_reminder(
                session,
                _context(),
                receivable_id=receivable_id,
                reminder=ReminderInput(channel="EMAIL"),
            )
        assert error.value.status_code == 409
        await receivables.send_real_reminder(
            session,
            _context(),
            receivable_id=receivable_id,
            reminder=ReminderInput(channel="EMAIL", resend_reason="El cliente pidió un reenvío."),
        )

    assert len(sent_emails) == 2

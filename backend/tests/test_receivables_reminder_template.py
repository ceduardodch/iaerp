"""El correo de cobro manual usa la plantilla configurada del tenant.

Antes el botón "Enviar recordatorio" mandaba un texto fijo ("Recordatorio de
pago") sin los datos bancarios ni la invitación a acordar un plan de pago,
mientras el recordatorio automático sí usaba la plantilla. El cliente recibía
dos mensajes distintos según quién lo disparara. Estas pruebas fijan que ambos
caminos rendericen la MISMA plantilla.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.masters import Party
from app.models.receivables import CollectionPolicy
from app.schemas.receivables import CollectionContactCreate, ReminderInput
from app.services import crm_integrations, receivables
from tests.test_billing_api import TENANT_A
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

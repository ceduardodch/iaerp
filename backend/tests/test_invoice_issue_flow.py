"""Integracion Fase 4 (E4-04/E4-05/E4-08): emision, transmision, reconciliacion.

Ciclo cubierto: ``POST /invoices/{id}/issue`` (firma sincrona + XML + RIDE +
MinIO + evento outbox ``invoice.signed``) seguido de ``consume_once`` con el
handler real (``workers.sri_transmission.handle_invoice_signed``) y
``SimulatorSRIClient`` in-memory, exactamente como correria en produccion via
Celery pero sin depender de un broker real.

Requiere MinIO real (``issue_document`` sube el XML/RIDE antes de que el
worker los pueda descargar): se omite automaticamente si MinIO no esta
disponible en ``localhost:9000``, igual que ``test_invoice_artifacts_api.py``.
"""

import socket
import uuid

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.integrations.sri.simulator import SimulatorSRIClient, get_store
from app.models.billing import DocumentArtifact, SalesDocument, SRITransmission
from app.models.platform import DeadLetter, OutboxEvent
from app.workers.outbox import OutboxMessage, claim_outbox_batch
from app.workers.sri_transmission import handle_invoice_signed
from tests.test_billing_api import (
    TENANT_A,
    _invoice_payload,
    _setup_billing_masters,
    auth,
    token_for,
)


def _minio_is_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 9000), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _minio_is_reachable(),
    reason="MinIO is not reachable at localhost:9000 in this environment",
)


async def _create_draft(client, key_prefix: str) -> tuple[str, str]:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["organization:write", "organization:read", "parties:write", "products:write"],
    )
    masters = await _setup_billing_masters(client, token, key_prefix=key_prefix)
    token_invoices = await token_for(
        client, "a@iaerp.local", TENANT_A, ["invoices:write", "invoices:read"]
    )
    response = await client.post(
        "/api/v1/invoices",
        headers=auth(token_invoices, f"{key_prefix}-draft-0001"),
        json=_invoice_payload(masters),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], token_invoices


async def _issue(client, token: str, invoice_id: str, idempotency_key: str):
    return await client.post(
        f"/api/v1/invoices/{invoice_id}/issue",
        headers=auth(token, idempotency_key),
    )


async def _claim_signed_event(invoice_id: str) -> OutboxMessage:
    async with SessionFactory() as session, session.begin():
        messages = await claim_outbox_batch(session)
    matching = [
        message
        for message in messages
        if message.event_type == "invoice.signed" and message.aggregate_id == invoice_id
    ]
    assert len(matching) == 1, f"expected exactly one invoice.signed event, got {len(matching)}"
    return matching[0]


@pytest.fixture(autouse=True)
def _reset_simulator():
    get_store().reset()
    yield
    get_store().reset()


async def test_full_cycle_draft_issue_consume_authorized(client) -> None:
    invoice_id, token = await _create_draft(client, "issue-happy")

    issue_response = await _issue(client, token, invoice_id, "issue-happy-0001")
    assert issue_response.status_code == 202, issue_response.text
    operation = issue_response.json()
    assert operation["status"] == "PROCESSING"

    get_response = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    assert get_response.status_code == 200
    signed_body = get_response.json()
    assert signed_body["status"] == "SIGNED"
    assert signed_body["accessKey"] is not None
    assert len(signed_body["accessKey"]) == 49

    artifacts_response = await client.get(
        f"/api/v1/invoices/{invoice_id}/artifacts", headers=auth(token)
    )
    artifact_types = {row["artifactType"] for row in artifacts_response.json()}
    assert artifact_types == {"xml-signed", "ride-pdf"}

    message = await _claim_signed_event(invoice_id)

    # Default simulator scenario: RECEIVED, then AUTHORIZED on second check.
    # handle_invoice_signed already performs send_reception + one
    # check_authorization synchronously, landing the document in
    # PENDING_AUTHORIZATION; a second consumption authorizes it, mirroring a
    # scheduled re-check in a real deployment.
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    mid_response = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    assert mid_response.json()["status"] == "PENDING_AUTHORIZATION"

    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    final_response = await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))
    final_body = final_response.json()
    assert final_body["status"] == "AUTHORIZED"
    assert final_body["authorizationNumber"] == final_body["accessKey"]
    assert final_body["authorizedAt"] is not None
    assert final_body["sriTransmission"]["status"] == "AUTHORIZED"
    assert final_body["sriTransmission"]["authorizationNumber"] == final_body["accessKey"]


async def test_full_cycle_returned_scenario_marks_document_rejected(client) -> None:
    invoice_id, token = await _create_draft(client, "issue-returned")
    issue_response = await _issue(client, token, invoice_id, "issue-returned-0001")
    assert issue_response.status_code == 202

    signed = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    get_store().set_scenario(signed["accessKey"], "RETURNED", reason="Esquema invalido")

    message = await _claim_signed_event(invoice_id)
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    final_body = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    assert final_body["status"] == "REJECTED"
    assert final_body["sriTransmission"]["status"] == "REJECTED"
    assert final_body["sriTransmission"]["message"] == "Esquema invalido"


async def test_full_cycle_not_authorized_scenario(client) -> None:
    invoice_id, token = await _create_draft(client, "issue-notauth")
    await _issue(client, token, invoice_id, "issue-notauth-0001")

    signed = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    get_store().set_scenario(
        signed["accessKey"], "NOT_AUTHORIZED", reason="Error en diferencias"
    )

    message = await _claim_signed_event(invoice_id)
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    final_body = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    assert final_body["status"] == "NOT_AUTHORIZED"
    assert final_body["sriTransmission"]["status"] == "NOT_AUTHORIZED"
    assert final_body["sriTransmission"]["message"] == "Error en diferencias"


async def test_reconciliation_never_retransmits_a_received_access_key(client) -> None:
    """E4-05: con una transmision RECEIVED previa, un TIMEOUT en recepcion nunca
    debe volver a llamar ``send_reception``; solo ``check_authorization``.
    """

    invoice_id, token = await _create_draft(client, "issue-reconcile")
    await _issue(client, token, invoice_id, "issue-reconcile-0001")
    signed = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    access_key = signed["accessKey"]

    message = await _claim_signed_event(invoice_id)

    # First consumption: default scenario, lands in RECEIVED->PENDING_AUTHORIZATION.
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    async with SessionFactory() as session:
        transmission = await session.scalar(
            select(SRITransmission).where(SRITransmission.access_key == access_key)
        )
        assert transmission is not None
        assert transmission.status == "PENDING_AUTHORIZATION"

    # Now force TIMEOUT for this access key and spy on send_reception.
    get_store().set_scenario(access_key, "TIMEOUT")

    class SpyClient(SimulatorSRIClient):
        def __init__(self) -> None:
            super().__init__()
            self.send_reception_calls = 0
            self.check_authorization_calls = 0

        async def send_reception(self, signed_xml, access_key):  # type: ignore[override]
            self.send_reception_calls += 1
            return await super().send_reception(signed_xml, access_key)

        async def check_authorization(self, access_key):  # type: ignore[override]
            self.check_authorization_calls += 1
            return await super().check_authorization(access_key)

    spy = SpyClient()
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=spy)
        await session.commit()

    assert spy.send_reception_calls == 0
    assert spy.check_authorization_calls == 1

    # The outbox event must have been rescheduled (not dead-lettered yet).
    async with SessionFactory() as session:
        outbox_event = await session.get(OutboxEvent, message.event_id)
        assert outbox_event is not None
        assert outbox_event.published_at is None
        assert outbox_event.dead_lettered_at is None

    # Only one SRITransmission row exists for the access key across both
    # consumptions (no duplicate transmission was ever recorded).
    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(SRITransmission)
            .where(SRITransmission.access_key == access_key)
        )
        assert count == 1


async def test_duplicate_response_scenario_does_not_create_second_authorization(client) -> None:
    invoice_id, token = await _create_draft(client, "issue-duplicate")
    await _issue(client, token, invoice_id, "issue-duplicate-0001")
    signed = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    access_key = signed["accessKey"]
    get_store().set_scenario(access_key, "DUPLICATE_RESPONSE")

    message = await _claim_signed_event(invoice_id)

    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    first_body = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    assert first_body["status"] == "AUTHORIZED"
    first_authorization_number = first_body["authorizationNumber"]

    # Re-run the handler again for the same access key/message (simulating
    # SRI/the simulator re-delivering the same AUTHORIZED response). The
    # reconciliation branch (already AUTHORIZED) only calls
    # check_authorization again, never a second send_reception, and the
    # document/authorization number stay exactly the same.
    async with SessionFactory() as session:
        await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
        await session.commit()

    second_body = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    assert second_body["status"] == "AUTHORIZED"
    assert second_body["authorizationNumber"] == first_authorization_number

    async with SessionFactory() as session:
        document = await session.get(SalesDocument, uuid.UUID(invoice_id))
        assert document is not None
        # Still a single sales document, never duplicated.
        count = await session.scalar(
            select(func.count()).select_from(SalesDocument).where(SalesDocument.id == document.id)
        )
        assert count == 1


async def test_persistent_technical_failure_reaches_dead_letter(client) -> None:
    invoice_id, token = await _create_draft(client, "issue-deadletter")
    await _issue(client, token, invoice_id, "issue-deadletter-0001")
    signed = (await client.get(f"/api/v1/invoices/{invoice_id}", headers=auth(token))).json()
    access_key = signed["accessKey"]
    get_store().set_scenario(access_key, "TIMEOUT")

    message = await _claim_signed_event(invoice_id)

    from app.core.config import get_settings

    settings = get_settings()
    # Con el escenario TIMEOUT el envio siempre falla tecnicamente. Cada
    # consumo agenda un OutboxEvent invoice.signed FRESCO (id nuevo, para
    # esquivar la deduplicacion del InboxEvent) con backoff; al alcanzar
    # OUTBOX_MAX_ATTEMPTS eventos acumulados, el handler crea un DeadLetter en
    # vez de seguir reintentando. Aqui simulamos esas re-entregas invocando el
    # handler en bucle (sin pasar por el dispatcher) hasta que aparezca el
    # dead letter.
    dead_letter = None
    for _ in range(settings.OUTBOX_MAX_ATTEMPTS + 2):
        async with SessionFactory() as session:
            await handle_invoice_signed(session, message, sri_client=SimulatorSRIClient())
            await session.commit()
        async with SessionFactory() as session:
            dead_letter = await session.scalar(
                select(DeadLetter).where(DeadLetter.source_id == message.event_id)
            )
        if dead_letter is not None:
            break

    assert dead_letter is not None
    assert dead_letter.payload["sales_document_id"] == invoice_id
    assert dead_letter.payload["access_key"] == access_key
    assert dead_letter.attempts >= settings.OUTBOX_MAX_ATTEMPTS


async def test_issue_idempotency_replay_returns_same_operation_without_duplicating_outbox(
    client,
) -> None:
    invoice_id, token = await _create_draft(client, "issue-idem")
    headers = auth(token, "issue-idempotent-0001")

    first = await client.post(f"/api/v1/invoices/{invoice_id}/issue", headers=headers)
    replay = await client.post(f"/api/v1/invoices/{invoice_id}/issue", headers=headers)
    assert first.status_code == 202, first.text
    assert replay.status_code == 202
    assert first.json() == replay.json()

    async with SessionFactory() as session:
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == TENANT_A,
                OutboxEvent.event_type == "invoice.signed",
                OutboxEvent.aggregate_id == invoice_id,
            )
        )
        assert outbox_count == 1

        artifact_count = await session.scalar(
            select(func.count())
            .select_from(DocumentArtifact)
            .where(DocumentArtifact.sales_document_id == uuid.UUID(invoice_id))
        )
        # Exactly two artifacts (xml-signed + ride-pdf), never duplicated by
        # the idempotency replay.
        assert artifact_count == 2

        operation_count = await session.scalar(
            select(func.count())
            .select_from(SalesDocument)
            .where(SalesDocument.id == uuid.UUID(invoice_id))
        )
        assert operation_count == 1

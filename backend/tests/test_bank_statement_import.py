import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.platform import AuditEvent
from app.models.receivables import Movement, Receivable
from app.workers.receivables import handle_invoice_authorized
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_flow import _insert_authorized_invoice, _message_for
from tests.test_receivables_payments_api import _create_receivable_via_event


def _statement(*rows: str) -> bytes:
    header = """CLIENTE: BTOB S.A.S.
RANGO: 01/01/2026 - 08/02/2026
CUENTA: 27059028731
MONEDA: DOLAR
FECHA REFERENCIA DESCRIPCION +/- VALOR SALDO CONTABLE SALDO DISPONIBLE OFICINA
"""
    return (header + "\n".join(rows) + "\n").encode()


def _row(
    *,
    occurred_at: str,
    reference: str,
    description: str,
    sign: str,
    amount: str,
) -> str:
    return "\t".join(
        (occurred_at, reference, description, sign, amount, "100.00", "100.00", "10101")
    )


async def test_bank_statement_preview_then_registers_only_unique_exact_match(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="bank-match",
        sequential="000000961",
        total=Decimal("150.00"),
        issue_date=date(2026, 1, 1),
    )
    receivable_id, _masters = await setup(client)
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    retention = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "bank-retention-0001"),
        json={
            "cashAmount": "0.00",
            "paymentDate": "2026-01-10",
            "retentions": [
                {
                    "kind": "RETENTION_RENTA",
                    "amount": "3.00",
                    "reason": "Código SRI 3440",
                    "documentReference": "1234567890123456789012345678901234567890123456789",
                },
                {
                    "kind": "RETENTION_IVA",
                    "amount": "10.50",
                    "reason": "Código SRI 2",
                    "documentReference": "1234567890123456789012345678901234567890123456789",
                },
            ],
            "discounts": [],
        },
    )
    assert retention.status_code == 201, retention.text
    content = _statement(
        _row(
            occurred_at="01/14/2026 13:32:00.000",
            reference="22525496-2451",
            description="1620 - TRANSF BCE RECIBIDA SPI2",
            sign="+",
            amount="136.50",
        ),
        _row(
            occurred_at="01/14/2026 13:33:00.000",
            reference="22525496-2452",
            description="1620 - TRANSF BCE RECIBIDA SPI2",
            sign="+",
            amount="99.99",
        ),
        _row(
            occurred_at="01/14/2026 13:34:00.000",
            reference="22525496-2453",
            description="1955 - TARIFA POR TRANSFERENCIA",
            sign="-",
            amount="0.45",
        ),
    )

    preview = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["totalRows"] == 3
    assert body["creditRows"] == 2
    assert body["period"] == "2026-01"
    assert body["outsidePeriodCreditCount"] == 0
    assert body["matchedCount"] == 1
    assert body["unmatchedCreditCount"] == 1
    assert body["ignoredDebitCount"] == 1
    assert body["alreadyImportedCount"] == 0
    assert body["matches"][0] | {"transactionId": body["matches"][0]["transactionId"]} == {
        "transactionId": body["matches"][0]["transactionId"],
        "paymentDate": "2026-01-14",
        "reference": "22525496-2451",
        "description": "1620 - TRANSF BCE RECIBIDA SPI2",
        "amount": "136.50",
        "receivableId": receivable_id,
        "invoiceSequential": "000000961",
        "originalAmount": "150.00",
        "retentionTotal": "13.50",
        "replacesManualPayment": False,
        "status": "MATCHED",
        "detail": "Lista para registrar",
    }
    async with SessionFactory() as session:
        payments_before = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(receivable_id),
                    Movement.movement_type == "PAYMENT",
                )
            )
        )
    assert payments_before == []

    headers = {**auth(token), "Idempotency-Key": "bank-statement-register-0001"}
    applied = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=headers,
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["matchedCount"] == 1
    assert applied.json()["matches"][0]["status"] == "REGISTERED"
    assert applied.json()["matches"][0]["detail"] == "Cobro registrado"

    replay = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=headers,
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == applied.json()

    another_key = await client.post(
        "/api/v1/receivables/bank-statement",
        headers={**auth(token), "Idempotency-Key": "bank-statement-register-0002"},
        data={"apply": "true", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert another_key.status_code == 200, another_key.text
    assert another_key.json()["matchedCount"] == 0
    assert another_key.json()["alreadyImportedCount"] == 1
    async with SessionFactory() as session:
        payments_after = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(receivable_id),
                    Movement.movement_type == "PAYMENT",
                )
            )
        )
    assert len(payments_after) == 1
    assert payments_after[0].amount == Decimal("136.50")
    assert payments_after[0].effective_date == date(2026, 1, 14)


async def test_bank_statement_does_not_guess_between_equal_invoices(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="bank-ambiguous",
        sequential="000000962",
        total=Decimal("100.00"),
        issue_date=date(2026, 1, 1),
    )
    _receivable_id, masters = await setup(client)
    second_document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000963",
        total=Decimal("100.00"),
        issue_date=date(2026, 1, 1),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(
            session,
            _message_for(second_document),
        )
        await session.commit()
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    content = _statement(
        _row(
            occurred_at="01/14/2026 13:32:00.000",
            reference="AMBIGUOUS-1",
            description="TRANSFERENCIA RECIBIDA",
            sign="+",
            amount="100.00",
        )
    )
    response = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matchedCount"] == 0
    assert response.json()["unmatchedCreditCount"] == 1
    assert response.json()["matches"] == []


async def test_bank_statement_period_replaces_manual_payment_with_bank_evidence(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="bank-period-replace",
        sequential="000000964",
        total=Decimal("2111.40"),
        issue_date=date(2026, 7, 1),
    )
    receivable_id, _masters = await setup(client)
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    manual = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "bank-manual-payment-0001"),
        json={
            "cashAmount": "1780.92",
            "paymentDate": "2026-07-30",
            "method": "TRANSFER",
            "reference": None,
            "retentions": [],
            "discounts": [],
        },
    )
    assert manual.status_code == 201, manual.text
    synthetic_authorization = "1" * 49
    retention = await client.post(
        f"/api/v1/receivables/{receivable_id}/payments",
        headers=auth(token, "bank-document-retention-0001"),
        json={
            "cashAmount": "0.00",
            "paymentDate": "2026-07-10",
            "retentions": [
                {
                    "kind": "RETENTION_RENTA",
                    "amount": "55.08",
                    "reason": "Código SRI 3440",
                    "documentReference": synthetic_authorization,
                },
                {
                    "kind": "RETENTION_IVA",
                    "amount": "275.40",
                    "reason": "Código SRI 2",
                    "documentReference": synthetic_authorization,
                },
            ],
            "discounts": [],
        },
    )
    assert retention.status_code == 201, retention.text
    content = _statement(
        *[
            _row(
                occurred_at=occurred_at,
                reference=f"UNIVERSIDAD-{month}",
                description="1416 - PAGO SERVICIOS VARIOS CASH",
                sign="+",
                amount="1780.92",
            )
            for month, occurred_at in (
                ("APR", "04/20/2026 13:32:00.000"),
                ("MAY", "05/15/2026 13:32:00.000"),
                ("JUN", "06/16/2026 13:32:00.000"),
                ("JUL", "07/14/2026 13:32:00.000"),
            )
        ]
    )

    preview = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(token),
        data={"apply": "false", "period": "2026-07"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["period"] == "2026-07"
    assert preview_body["creditRows"] == 1
    assert preview_body["outsidePeriodCreditCount"] == 3
    assert preview_body["matchedCount"] == 1
    assert preview_body["matches"][0]["replacesManualPayment"] is True
    assert preview_body["matches"][0]["detail"] == (
        "Reemplazará cobro manual con respaldo bancario"
    )

    applied = await client.post(
        "/api/v1/receivables/bank-statement",
        headers={**auth(token), "Idempotency-Key": "bank-period-replace-0001"},
        data={"apply": "true", "period": "2026-07"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["matches"][0]["detail"] == (
        "Cobro manual reemplazado con respaldo bancario"
    )
    async with SessionFactory() as session:
        movements = list(
            await session.scalars(
                select(Movement).where(Movement.receivable_id == uuid.UUID(receivable_id))
            )
        )
    payments = [movement for movement in movements if movement.movement_type == "PAYMENT"]
    reversals = [movement for movement in movements if movement.movement_type == "REVERSAL"]
    retentions = [movement for movement in movements if movement.movement_type == "RETENTION"]
    assert len(payments) == 2
    assert len(reversals) == 1
    assert len(retentions) == 2
    manual_payment = next(movement for movement in payments if movement.support_reference is None)
    bank_payment = next(movement for movement in payments if movement.support_reference is not None)
    assert reversals[0].reversed_movement_id == manual_payment.id
    assert bank_payment.effective_date == date(2026, 7, 14)
    assert bank_payment.support_reference.startswith("BANCO UNIVERSIDAD-JUL | ")
    assert sum((movement.amount for movement in retentions), Decimal("0.00")) == Decimal("330.48")


async def test_uploaded_bank_evidence_reverses_manual_payment_on_future_invoice(client) -> None:
    setup = await _create_receivable_via_event(
        key_prefix="bank-document-priority",
        sequential="000000965",
        total=Decimal("150.00"),
        issue_date=date(2026, 7, 1),
    )
    target_receivable_id, masters = await setup(client)
    token = await token_for(
        client, "a@iaerp.local", TENANT_A, ["receivables:write", "receivables:read"]
    )
    retention = await client.post(
        f"/api/v1/receivables/{target_receivable_id}/payments",
        headers=auth(token, "bank-priority-retention-0001"),
        json={
            "cashAmount": "0.00",
            "paymentDate": "2026-07-10",
            "retentions": [
                {
                    "kind": "RETENTION_RENTA",
                    "amount": "3.00",
                    "reason": "Código SRI 3440",
                    "documentReference": "2" * 49,
                },
                {
                    "kind": "RETENTION_IVA",
                    "amount": "10.50",
                    "reason": "Código SRI 2",
                    "documentReference": "2" * 49,
                },
            ],
            "discounts": [],
        },
    )
    assert retention.status_code == 201, retention.text
    content = _statement(
        _row(
            occurred_at="07/14/2026 13:32:00.000",
            reference="DOCUMENT-PRIORITY-1",
            description="TRANSFERENCIA RECIBIDA",
            sign="+",
            amount="136.50",
        )
    )
    registered = await client.post(
        "/api/v1/receivables/bank-statement",
        headers={**auth(token), "Idempotency-Key": "bank-document-priority-0001"},
        data={"apply": "true", "period": "2026-07"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["matchedCount"] == 1

    future_document = await _insert_authorized_invoice(
        tenant_id=TENANT_A,
        establishment_id=uuid.UUID(masters["establishment_id"]),
        emission_point_id=uuid.UUID(masters["emission_point_id"]),
        party_id=uuid.UUID(masters["party_id"]),
        product_id=uuid.UUID(masters["product_id"]),
        sequential="000000966",
        total=Decimal("200.00"),
        issue_date=date(2026, 7, 17),
    )
    async with SessionFactory() as session:
        await handle_invoice_authorized(session, _message_for(future_document))
        await session.commit()
    future_receivable_response = await client.get(
        "/api/v1/receivables", headers=auth(token)
    )
    assert future_receivable_response.status_code == 200
    future_receivable_id = next(
        item["id"]
        for item in future_receivable_response.json()
        if item["invoiceSequential"] == "000000966"
    )
    manual = await client.post(
        f"/api/v1/receivables/{future_receivable_id}/payments",
        headers=auth(token, "bank-priority-manual-0001"),
        json={
            "cashAmount": "136.50",
            "paymentDate": "2026-07-30",
            "method": "TRANSFER",
            "reference": None,
            "retentions": [],
            "discounts": [],
        },
    )
    assert manual.status_code == 201, manual.text

    preview = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(token),
        data={"apply": "false", "period": "2026-07"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    correction = preview.json()["manualCorrections"][0]
    assert preview.json()["matchedCount"] == 0
    assert preview.json()["alreadyImportedCount"] == 1
    assert preview.json()["manualCorrectionCount"] == 1
    assert correction["targetInvoiceSequential"] == "000000965"
    assert correction["manualInvoiceSequential"] == "000000966"
    assert correction["status"] == "CORRECTION_REQUIRED"

    outer_idempotency_key = "bank-document-priority-" + ("x" * 105)
    assert len(outer_idempotency_key) == 128
    applied = await client.post(
        "/api/v1/receivables/bank-statement",
        headers={**auth(token), "Idempotency-Key": outer_idempotency_key},
        data={"apply": "true", "period": "2026-07"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["manualCorrections"][0]["status"] == "CORRECTED"
    async with SessionFactory() as session:
        future_movements = list(
            await session.scalars(
                select(Movement).where(
                    Movement.receivable_id == uuid.UUID(future_receivable_id)
                )
            )
        )
        original_payment = next(
            item for item in future_movements if item.movement_type == "PAYMENT"
        )
        future_receivable = await session.get(Receivable, uuid.UUID(future_receivable_id))
        reversal_audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A,
                    AuditEvent.action == "movement.reversed",
                    AuditEvent.entity_id == str(original_payment.id),
                )
            )
        )
    assert len([item for item in future_movements if item.movement_type == "PAYMENT"]) == 1
    assert len([item for item in future_movements if item.movement_type == "REVERSAL"]) == 1
    assert future_receivable is not None
    assert future_receivable.status == "OPEN"
    assert reversal_audits
    assert all(
        event.idempotency_key is not None and len(event.idempotency_key) <= 128
        for event in reversal_audits
    )


async def test_bank_statement_requires_supported_file_and_write_scope(client) -> None:
    read_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    forbidden = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(read_token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", _statement(), "text/plain")},
    )
    assert forbidden.status_code == 403
    write_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    invalid = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(write_token),
        data={"apply": "false", "period": "2026-01"},
        files={"file": ("estado.txt", b"not a bank statement", "text/plain")},
    )
    assert invalid.status_code == 422
    invalid_period = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(write_token),
        data={"apply": "false", "period": "2026-13"},
        files={
            "file": (
                "estado.txt",
                _statement(
                    _row(
                        occurred_at="01/14/2026 13:32:00.000",
                        reference="PERIOD-1",
                        description="TRANSFERENCIA RECIBIDA",
                        sign="+",
                        amount="100.00",
                    )
                ),
                "text/plain",
            )
        },
    )
    assert invalid_period.status_code == 422

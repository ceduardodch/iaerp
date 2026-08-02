import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.receivables import Movement
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
        data={"apply": "false"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["totalRows"] == 3
    assert body["creditRows"] == 2
    assert body["matchedCount"] == 1
    assert body["unmatchedCreditCount"] == 1
    assert body["ignoredDebitCount"] == 1
    assert body["alreadyImportedCount"] == 0
    assert body["matches"][0] | {
        "transactionId": body["matches"][0]["transactionId"]
    } == {
        "transactionId": body["matches"][0]["transactionId"],
        "paymentDate": "2026-01-14",
        "reference": "22525496-2451",
        "description": "1620 - TRANSF BCE RECIBIDA SPI2",
        "amount": "136.50",
        "receivableId": receivable_id,
        "invoiceSequential": "000000961",
        "originalAmount": "150.00",
        "retentionTotal": "13.50",
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
        data={"apply": "true"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["matchedCount"] == 1
    assert applied.json()["matches"][0]["status"] == "REGISTERED"
    assert applied.json()["matches"][0]["detail"] == "Cobro registrado"

    replay = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=headers,
        data={"apply": "true"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == applied.json()

    another_key = await client.post(
        "/api/v1/receivables/bank-statement",
        headers={**auth(token), "Idempotency-Key": "bank-statement-register-0002"},
        data={"apply": "true"},
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
        data={"apply": "false"},
        files={"file": ("estado.txt", content, "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matchedCount"] == 0
    assert response.json()["unmatchedCreditCount"] == 1
    assert response.json()["matches"] == []


async def test_bank_statement_requires_supported_file_and_write_scope(client) -> None:
    read_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])
    forbidden = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(read_token),
        data={"apply": "false"},
        files={"file": ("estado.txt", _statement(), "text/plain")},
    )
    assert forbidden.status_code == 403
    write_token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:write"])
    invalid = await client.post(
        "/api/v1/receivables/bank-statement",
        headers=auth(write_token),
        data={"apply": "false"},
        files={"file": ("estado.txt", b"not a bank statement", "text/plain")},
    )
    assert invalid.status_code == 422

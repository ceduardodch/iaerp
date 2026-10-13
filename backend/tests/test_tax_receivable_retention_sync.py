"""Synthetic end-to-end tax evidence -> customer balance reconciliation."""

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import SessionFactory, engine
from app.models.platform import AuditEvent
from app.models.receivables import Movement, Receivable
from app.models.tax import FiscalDocument, TaxEvidence
from app.schemas.receivables import PaymentInput
from app.services import receivables, storage
from app.services.tax.ingest import upsert_parsed_document
from app.services.tax.receivable_retentions import (
    sync_receivable_retentions,
    sync_tenant_retentions,
)
from app.services.tax.sri_xml import parse_authorized_document
from tests.test_receivables_payment_service import _context, _create_receivable
from tests.test_receivables_service import _create_authorized_invoice_stub, _create_party

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RUC = "1799999999001"
AUTH = "7" * 49


def xml_for(issuer, support, *, subject=RUC, amount="10.00", authorization=AUTH):
    return f"""<autorizacion><estado>AUTORIZADO</estado>
<numeroAutorizacion>{authorization}</numeroAutorizacion><comprobante><![CDATA[
<comprobanteRetencion version="1.0.0"><infoTributaria><ruc>{issuer}</ruc>
<razonSocial>TEST CUSTOMER</razonSocial><claveAcceso>{authorization}</claveAcceso>
<estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000000099</secuencial></infoTributaria>
<infoCompRetencion><fechaEmision>05/07/2026</fechaEmision>
<identificacionSujetoRetenido>{subject}</identificacionSujetoRetenido></infoCompRetencion>
<impuestos><impuesto><codigo>1</codigo><codigoRetencion>303</codigoRetencion>
<baseImponible>100.00</baseImponible><porcentajeRetener>10</porcentajeRetener>
<valorRetenido>{amount}</valorRetenido><codDocSustento>01</codDocSustento>
<numDocSustento>{support}</numDocSustento>
</impuesto></impuestos></comprobanteRetencion>]]></comprobante></autorizacion>""".encode()


async def setup_invoice(session, *, tenant=TENANT_A, total="100.00", suffix="100"):
    party = await _create_party(session, tenant_id=tenant, suffix=suffix)
    invoice = await _create_authorized_invoice_stub(
        session, tenant_id=tenant, party_id=party.id, total=Decimal(total)
    )
    receivable, _ = await _create_receivable(
        session,
        tenant_id=tenant,
        party_id=party.id,
        sales_document_id=invoice.id,
        original_amount=Decimal(total),
        installment_amounts=[Decimal(total)],
        due_date=date(2026, 7, 31),
    )
    return receivable, party, f"900900{invoice.sequential}"


async def ingest(session, payload, *, evidence_id=None):
    return await upsert_parsed_document(
        session,
        _context(tenant_id=TENANT_A),
        parsed=parse_authorized_document(payload),
        tenant_ruc=RUC,
        evidence_id=evidence_id,
    )


async def balance(session, entity):
    return await receivables.compute_receivable_balance(
        session, tenant_id=entity.tenant_id, receivable=entity
    )


async def test_ingest_applies_authorized_retention_and_reimport_does_not_duplicate(client):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        payload = xml_for(party.identification_number, number)
        document, created = await ingest(session, payload)
        assert created
        assert await balance(session, debt) == Decimal("90.00")
        repeated, created = await ingest(session, payload)
        assert not created and repeated.id == document.id
        assert await balance(session, debt) == Decimal("90.00")
        movements = list(await session.scalars(select(Movement)))
        assert len(movements) == 1
        assert movements[0].movement_type == "RETENTION"
        assert movements[0].effective_date == date(2026, 7, 5)
        assert (
            len(
                list(
                    await session.scalars(
                        select(AuditEvent).where(AuditEvent.action == "retention.tax_applied")
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize("fault", ["subject", "issuer", "series", "excess", "voided"])
async def test_commercial_conflict_preserves_fiscal_import_without_settlement(client, fault):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        if fault == "voided":
            debt.status = "VOIDED"
        payload = xml_for(
            "1790000000001" if fault == "issuer" else party.identification_number,
            "001001000000001" if fault == "series" else number,
            subject="1799999999002" if fault == "subject" else RUC,
            amount="101.00" if fault == "excess" else "10.00",
        )
        document, created = await ingest(session, payload)
        assert created and document.doc_type == "RETENCION"
        assert not document.is_preliminary
        assert await balance(session, debt) == Decimal("100.00")
        assert list(await session.scalars(select(Movement))) == []


async def test_cross_tenant_receivable_is_not_touched(client):
    async with SessionFactory() as session, session.begin():
        other, party, number = await setup_invoice(session, tenant=TENANT_B)
        await ingest(session, xml_for(party.identification_number, number))
        assert await balance(session, other) == Decimal("100.00")
        assert list(await session.scalars(select(Movement))) == []


async def store_evidence(session, payload, monkeypatch):
    async def download(**kwargs):
        return payload

    monkeypatch.setattr(storage, "download_artifact", download)
    evidence = TaxEvidence(
        tenant_id=TENANT_A,
        filename="synthetic.xml",
        file_type="XML",
        object_key="tenant-a/synthetic.xml",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        origin="MANUAL",
        uploaded_at=datetime.now(UTC),
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def test_existing_document_reconciles_after_invoice_created_then_cash_settles(
    client, monkeypatch
):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        debt.status = "VOIDED"  # initially unavailable commercially
        payload = xml_for(party.identification_number, number)
        evidence = await store_evidence(session, payload, monkeypatch)
        await ingest(session, payload, evidence_id=evidence.id)
        debt.status = "OPEN"
        await session.flush()
        result = await sync_receivable_retentions(
            session,
            _context(tenant_id=TENANT_A),
            debt.id,
            correlation_id="prepare",
            idempotency_key="prepare-one",
        )
        assert result.applied == 1 and result.pending == 0
        assert await balance(session, debt) == Decimal("90.00")
        repeated = await sync_tenant_retentions(
            session,
            _context(tenant_id=TENANT_A),
            correlation_id="repeat",
            idempotency_key="repeat-one",
        )
        assert repeated.applied == 0 and repeated.omitted == 1
        await receivables.record_payment(
            session,
            _context(tenant_id=TENANT_A),
            debt.id,
            PaymentInput(cash_amount=Decimal("90.00"), payment_date=date(2026, 7, 7)),
            correlation_id="cash",
            idempotency_key="cash-one",
        )
        assert await balance(session, debt) == Decimal("0.00")
        assert [row.movement_type for row in await session.scalars(select(Movement))] == [
            "RETENTION",
            "PAYMENT",
        ]


async def test_missing_or_tampered_xml_requires_review_not_default(client, monkeypatch):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        debt.status = "VOIDED"
        payload = xml_for(party.identification_number, number)
        evidence = await store_evidence(session, payload, monkeypatch)
        document, _ = await ingest(session, payload, evidence_id=evidence.id)
        debt.status = "OPEN"
        evidence.sha256 = "0" * 64
        await session.flush()
        result = await sync_tenant_retentions(
            session,
            _context(tenant_id=TENANT_A),
            correlation_id="check",
            idempotency_key="check-one",
        )
        assert result.pending == 1 and result.notes == ["RETENTION_XML_UNAVAILABLE"]
        document.evidence_id = None
        await session.flush()
        result = await sync_tenant_retentions(
            session,
            _context(tenant_id=TENANT_A),
            correlation_id="check2",
            idempotency_key="check-two",
        )
        assert result.pending == 1 and result.notes == ["RETENTION_XML_REQUIRED"]
        assert await balance(session, debt) == Decimal("100.00")
        assert list(await session.scalars(select(FiscalDocument)))
        assert list(await session.scalars(select(Movement))) == []


async def test_manual_same_authorization_is_not_applied_twice(client):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        await receivables.record_payment(
            session,
            _context(tenant_id=TENANT_A),
            debt.id,
            PaymentInput(
                cash_amount=Decimal("0.00"),
                payment_date=date(2026, 7, 5),
                retentions=[
                    {
                        "kind": "RETENTION_RENTA",
                        "amount": "10.00",
                        "document_reference": AUTH,
                        "reason": "Manual",
                    }
                ],
            ),
            correlation_id="manual",
            idempotency_key="manual-one",
        )
        await ingest(session, xml_for(party.identification_number, number))
        assert await balance(session, debt) == Decimal("90.00")
        assert len(list(await session.scalars(select(Movement)))) == 1


async def test_reversed_retention_is_not_restored_on_reimport(client):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        payload = xml_for(party.identification_number, number)
        await ingest(session, payload)
        movement = await session.scalar(select(Movement))
        await receivables.reverse_movement(
            session,
            _context(tenant_id=TENANT_A),
            receivable_id=debt.id,
            movement_id=movement.id,
            reason="Operator review",
            correlation_id="reverse",
            idempotency_key="reverse-one",
        )
        await ingest(session, payload)
        assert await balance(session, debt) == Decimal("100.00")
        assert len(list(await session.scalars(select(Movement)))) == 2


@pytest.mark.parametrize("fault", ["support-type", "invoice-draft", "existing-conflict"])
async def test_ambiguous_commercial_evidence_requires_review(client, fault):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        payload = xml_for(party.identification_number, number)
        if fault == "support-type":
            payload = payload.replace(b"<codDocSustento>01", b"<codDocSustento>04")
        if fault == "invoice-draft":
            from app.models.billing import SalesDocument

            invoice = await session.get(SalesDocument, debt.sales_document_id)
            invoice.status = "DRAFT"
        if fault == "existing-conflict":
            await receivables.record_payment(
                session,
                _context(tenant_id=TENANT_A),
                debt.id,
                PaymentInput(
                    cash_amount=Decimal("0.00"),
                    payment_date=date(2026, 7, 5),
                    retentions=[
                        {
                            "kind": "RETENTION_RENTA",
                            "amount": "5.00",
                            "document_reference": AUTH,
                            "reason": "Manual",
                        }
                    ],
                ),
                correlation_id="manual",
                idempotency_key="manual-one",
            )
        await session.flush()
        await ingest(session, payload)
        expected = Decimal("95.00") if fault == "existing-conflict" else Decimal("100.00")
        assert await balance(session, debt) == expected
        assert len(list(await session.scalars(select(Movement)))) == (fault == "existing-conflict")


async def test_multiple_supporting_invoices_in_one_authorization_and_repeated_lines(client):
    async with SessionFactory() as session, session.begin():
        first, party, first_number = await setup_invoice(session)
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("100.00")
        )
        second, _ = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("100.00"),
            installment_amounts=[Decimal("100.00")],
            due_date=date(2026, 7, 31),
        )
        payload = xml_for(party.identification_number, first_number)
        start, end = payload.index(b"<impuesto>"), payload.index(b"</impuesto>") + 11
        line = payload[start:end]
        second_line = line.replace(first_number.encode(), f"900900{invoice.sequential}".encode())
        payload = payload[:start] + line + line + second_line + payload[end:]
        await ingest(session, payload)
        assert await balance(session, first) == Decimal("80.00")
        assert await balance(session, second) == Decimal("90.00")
        await ingest(session, payload)
        assert len(list(await session.scalars(select(Movement)))) == 2


async def test_v2_supporting_document_type_and_amount_are_applied(client):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        payload = xml_for(party.identification_number, number)
        payload = payload.replace(b'version="1.0.0"', b'version="2.0.0"')
        payload = payload.replace(
            b"<impuestos><impuesto>",
            (
                f"<docsSustento><docSustento><codDocSustento>01</codDocSustento>"
                f"<numDocSustento>{number}</numDocSustento><retenciones><retencion>"
            ).encode(),
        ).replace(
            b"</impuesto></impuestos>", b"</retencion></retenciones></docSustento></docsSustento>"
        )
        await ingest(session, payload)
        assert await balance(session, debt) == Decimal("90.00")


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="Real row locks require PostgreSQL")
async def test_concurrent_historical_reconciliation_applies_only_once(client, monkeypatch):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        debt.status = "VOID"
        payload = xml_for(party.identification_number, number)
        evidence = await store_evidence(session, payload, monkeypatch)
        await ingest(session, payload, evidence_id=evidence.id)
        debt.status = "OPEN"

    async def run(key):
        async with SessionFactory() as session, session.begin():
            return await sync_receivable_retentions(
                session,
                _context(tenant_id=TENANT_A),
                debt.id,
                correlation_id=key,
                idempotency_key=key,
            )

    results = await asyncio.gather(run("parallel-a"), run("parallel-b"))
    assert sum(result.applied for result in results) == 1
    assert sum(result.omitted for result in results) == 1
    async with SessionFactory() as session:
        assert len(list(await session.scalars(select(Movement)))) == 1


async def test_bank_preview_matches_documented_net_without_writes_then_confirm_settles(
    client, monkeypatch
):
    from app.services.bank_reconciliation import import_bank_statement
    from tests.test_bank_statement_import import _row, _statement

    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        debt.status = "VOID"
        payload = xml_for(party.identification_number, number)
        evidence = await store_evidence(session, payload, monkeypatch)
        await ingest(session, payload, evidence_id=evidence.id)
        debt.status = "OPEN"
        debt_id = debt.id
    content = _statement(
        _row(
            occurred_at="07/07/2026 13:32:00.000",
            reference="SYNTHETIC-DEPOSIT-90",
            description="TRANSFER RECEIVED",
            sign="+",
            amount="90.00",
        )
    )
    async with SessionFactory() as session, session.begin():
        preview = await import_bank_statement(
            session,
            context=_context(tenant_id=TENANT_A),
            file_name="synthetic.txt",
            content=content,
            period=date(2026, 7, 1),
            apply=False,
            correlation_id="preview-bank",
            idempotency_key="preview-bank-one",
        )
        assert preview.matched_count == 1
        assert preview.matches[0].retention_total == Decimal("10.00")
        assert preview.matches[0].amount == Decimal("90.00")
        assert list(await session.scalars(select(Movement))) == []
        assert list(await session.scalars(select(AuditEvent))) == []
        fresh = await session.get(Receivable, debt_id)
        assert await balance(session, fresh) == Decimal("100.00")
    async with SessionFactory() as session, session.begin():
        confirmed = await import_bank_statement(
            session,
            context=_context(tenant_id=TENANT_A),
            file_name="synthetic.txt",
            content=content,
            period=date(2026, 7, 1),
            apply=True,
            correlation_id="confirm-bank",
            idempotency_key="confirm-bank-one",
        )
        assert confirmed.matches[0].status == "REGISTERED"
        fresh = await session.get(Receivable, debt_id)
        assert await balance(session, fresh) == Decimal("0.00")
    async with SessionFactory() as session, session.begin():
        await import_bank_statement(
            session,
            context=_context(tenant_id=TENANT_A),
            file_name="synthetic.txt",
            content=content,
            period=date(2026, 7, 1),
            apply=True,
            correlation_id="repeat-bank",
            idempotency_key="confirm-bank-two",
        )
        assert len(list(await session.scalars(select(Movement)))) == 2


async def test_cash_request_cannot_include_already_applied_tax_retention(client):
    async with SessionFactory() as session, session.begin():
        debt, party, number = await setup_invoice(session)
        await ingest(session, xml_for(party.identification_number, number))
        with pytest.raises(HTTPException) as failure:
            await receivables.record_payment(
                session,
                _context(tenant_id=TENANT_A),
                debt.id,
                PaymentInput(
                    cash_amount=Decimal("50.00"),
                    payment_date=date(2026, 7, 7),
                    retentions=[
                        {
                            "kind": "RETENTION_RENTA",
                            "amount": "10.00",
                            "document_reference": AUTH,
                            "reason": "Duplicate",
                        }
                    ],
                ),
                correlation_id="duplicate",
                idempotency_key="duplicate-one",
            )
        assert failure.value.status_code == 422
        assert await balance(session, debt) == Decimal("90.00")
        assert len(list(await session.scalars(select(Movement)))) == 1

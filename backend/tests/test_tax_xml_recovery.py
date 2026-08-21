"""Recuperación durable de XML recibidos usando claves ya conocidas."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.db.session import SessionFactory
from app.integrations.sri.protocol import AuthorizationResult
from app.models.payables import Payable, PayableInstallment, PayableMovement
from app.models.platform import AuditEvent, OutboxEvent, Tenant
from app.models.tax import (
    FiscalDocument,
    FiscalDocumentTax,
    TaxPeriod,
    TaxXmlRecoveryItem,
    TaxXmlRecoveryJob,
)
from app.services import access_key
from app.services.access_key import AccessKeyInput
from app.services.tax import evidence as evidence_service
from app.workers import tax_xml_recovery as recovery_worker
from app.workers.outbox import OutboxMessage
from app.workers.tax_xml_recovery import RecoveryAlreadyRunningError, run_recovery_job
from tests.fixtures.sri_documents import CREDIT_NOTE_RECEIVED_IVA15_XML

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
RECEIVER_RUC = "0777777777001"
ISSUER_RUC = "0888888888001"
FIXTURE = Path(__file__).parent / "fixtures" / "sri" / "factura_recibida_iva15.xml"


def _valid_key() -> str:
    return access_key.build_access_key(
        AccessKeyInput(
            issue_date=date(2025, 11, 11),
            document_code="01",
            ruc=ISSUER_RUC,
            environment="2",
            establishment_code="001",
            emission_point_code="002",
            sequential="000019877",
            numeric_code="27952129",
            emission_type="1",
        )
    )


def _valid_key_for_sequence(sequence: int) -> str:
    return access_key.build_access_key(
        AccessKeyInput(
            issue_date=date(2025, 11, 11),
            document_code="01",
            ruc=ISSUER_RUC,
            environment="2",
            establishment_code="001",
            emission_point_code="002",
            sequential=f"{sequence:09d}",
            numeric_code="27952129",
            emission_type="1",
        )
    )


def _authorized_xml(key: str, *, receiver_ruc: str = RECEIVER_RUC) -> bytes:
    payload = FIXTURE.read_bytes()
    payload = payload.replace(
        b"1111202501098888888800120010020000198772795212911",
        key.encode(),
    )
    return payload.replace(RECEIVER_RUC.encode(), receiver_ruc.encode())


def _valid_credit_note_key() -> str:
    return access_key.build_access_key(
        AccessKeyInput(
            issue_date=date(2025, 11, 21),
            document_code="04",
            ruc=ISSUER_RUC,
            environment="2",
            establishment_code="001",
            emission_point_code="002",
            sequential="000000111",
            numeric_code="12345678",
            emission_type="1",
        )
    )


def _authorized_credit_note_xml(key: str) -> bytes:
    return CREDIT_NOTE_RECEIVED_IVA15_XML.replace(
        b"2111202504098888888800120010020000001111234567811",
        key.encode(),
    )


async def _token(
    client,
    *,
    tenant_id: uuid.UUID = TENANT_A,
    email: str = "a@iaerp.local",
    scopes: list[str] | None = None,
) -> str:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "email": email,
            "tenantId": str(tenant_id),
            "scopes": scopes or ["tax:read", "tax:write"],
        },
    )
    assert response.status_code == 200
    return response.json()["accessToken"]


def _auth(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


async def _seed_preliminary() -> tuple[uuid.UUID, uuid.UUID, str]:
    key = _valid_key()
    async with SessionFactory() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == TENANT_A).values(ruc=RECEIVER_RUC))
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2025,
            month=11,
            obligation_type="IVA",
            status="EVIDENCIA_INCOMPLETA",
        )
        session.add(period)
        await session.flush()
        document = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="RECIBIDO",
            doc_type="FACTURA",
            access_key=key,
            issue_date=date(2025, 11, 11),
            counterparty_identification=ISSUER_RUC,
            counterparty_name="PROVEEDOR IVA DEMO",
            subtotal=Decimal("13.13"),
            tax_total=Decimal("1.97"),
            total=Decimal("15.10"),
            is_preliminary=True,
        )
        session.add(document)
        await session.flush()
        return period.id, document.id, key


async def _seed_preliminary_credit_note() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]:
    invoice_key = _valid_key()
    credit_note_key = _valid_credit_note_key()
    async with SessionFactory() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == TENANT_A).values(ruc=RECEIVER_RUC))
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2025,
            month=11,
            obligation_type="IVA",
            status="EVIDENCIA_INCOMPLETA",
        )
        session.add(period)
        await session.flush()
        invoice = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="RECIBIDO",
            doc_type="FACTURA",
            access_key=invoice_key,
            authorization_number=invoice_key,
            issue_date=date(2025, 11, 11),
            establishment_code="001",
            emission_point_code="002",
            sequential="000019877",
            counterparty_identification=ISSUER_RUC,
            counterparty_name="PROVEEDOR IVA DEMO",
            subtotal=Decimal("13.13"),
            tax_total=Decimal("1.97"),
            total=Decimal("15.10"),
            is_preliminary=False,
        )
        session.add(invoice)
        await session.flush()
        payable = Payable(
            tenant_id=TENANT_A,
            fiscal_document_id=invoice.id,
            supplier_id=None,
            supplier_name="PROVEEDOR IVA DEMO",
            description="Factura de prueba",
            category="Sin clasificar",
            document_type="INVOICE",
            document_number="001-002-000019877",
            issue_date=date(2025, 11, 11),
            due_date=date(2025, 11, 11),
            total=Decimal("15.10"),
            status="OPEN",
            tax_classification="DEDUCTIBLE_PENDING_REVIEW",
            evidence_status="FISCAL_XML",
        )
        session.add(payable)
        await session.flush()
        session.add(
            PayableInstallment(
                tenant_id=TENANT_A,
                payable_id=payable.id,
                sequence=1,
                due_date=date(2025, 11, 11),
                amount=Decimal("15.10"),
            )
        )
        note = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="RECIBIDO",
            doc_type="NOTA_CREDITO",
            access_key=credit_note_key,
            issue_date=date(2025, 11, 21),
            counterparty_identification=ISSUER_RUC,
            counterparty_name="PROVEEDOR IVA DEMO",
            subtotal=Decimal("5.00"),
            tax_total=Decimal("0.75"),
            total=Decimal("5.75"),
            is_preliminary=True,
        )
        session.add(note)
        await session.flush()
        return period.id, note.id, payable.id, credit_note_key


class FakeSRIClient:
    def __init__(self, xml: bytes) -> None:
        self.xml = xml
        self.calls = 0

    async def send_reception(self, signed_xml: bytes, access_key: str):  # pragma: no cover
        raise NotImplementedError

    async def check_authorization(self, access_key: str) -> AuthorizationResult:
        self.calls += 1
        return AuthorizationResult(
            status="AUTHORIZED",
            authorization_number=access_key,
            authorized_xml=self.xml,
        )


async def test_recovery_job_ingests_xml_and_completes_period(client, monkeypatch) -> None:
    period_id, document_id, key = await _seed_preliminary()
    stored: dict[str, bytes] = {}

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        stored[object_key] = data

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    token = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-2025-11"),
    )
    assert created.status_code == 201, created.text
    job_id = uuid.UUID(created.json()["id"])

    fake = FakeSRIClient(_authorized_xml(key))
    await run_recovery_job(job_id, sri_client=fake)

    async with SessionFactory() as session:
        job = await session.get(TaxXmlRecoveryJob, job_id)
        item = await session.scalar(
            select(TaxXmlRecoveryItem).where(TaxXmlRecoveryItem.job_id == job_id)
        )
        document = await session.get(FiscalDocument, document_id)
        period = await session.get(TaxPeriod, period_id)
        taxes = list(
            await session.scalars(
                select(FiscalDocumentTax).where(
                    FiscalDocumentTax.tenant_id == TENANT_A,
                    FiscalDocumentTax.fiscal_document_id == document_id,
                )
            )
        )
        audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == TENANT_A,
                    AuditEvent.action == "tax.evidence.sri_recovered",
                )
            )
        )
        events = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == TENANT_A,
                    OutboxEvent.event_type == "tax.evidence.sri_recovered",
                )
            )
        )

    assert fake.calls == 1
    assert job is not None and job.status == "COMPLETED"
    assert item is not None and item.status == "RECOVERED"
    assert (job.processed_count, job.recovered_count, job.failed_count) == (1, 1, 0)
    assert document is not None and document.is_preliminary is False
    assert period is not None and period.status == "LISTO_REVISAR"
    assert len(taxes) == 1 and taxes[0].tax_bracket == "GRAVADO"
    assert len(stored) == 1
    assert len(audits) == 1
    assert len(events) == 1


async def test_recovery_rejects_xml_for_another_tenant(client, monkeypatch) -> None:
    period_id, document_id, key = await _seed_preliminary()

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        raise AssertionError("Untrusted XML must not be stored")

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    token = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-wrong-tenant"),
    )
    job_id = uuid.UUID(created.json()["id"])

    await run_recovery_job(
        job_id,
        sri_client=FakeSRIClient(_authorized_xml(key, receiver_ruc="0999999999001")),
    )

    async with SessionFactory() as session:
        job = await session.get(TaxXmlRecoveryJob, job_id)
        item = await session.scalar(
            select(TaxXmlRecoveryItem).where(TaxXmlRecoveryItem.job_id == job_id)
        )
        document = await session.get(FiscalDocument, document_id)
    assert job is not None and (job.failed_count, job.recovered_count) == (1, 0)
    assert item is not None and item.status == "FAILED"
    assert document is not None and document.is_preliminary is True
    status = await client.get(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token),
    )
    assert status.status_code == 200, status.text
    assert status.json()["items"] == [
        {"documentId": str(document_id), "status": "FAILED"}
    ]


async def test_recovery_requires_write_scope_and_hides_jobs_from_other_tenants(client) -> None:
    period_id, _document_id, _key = await _seed_preliminary()
    read_only = await _token(client, scopes=["tax:read"])
    denied = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(read_only, "recover-xml-read-only"),
    )
    assert denied.status_code == 403

    owner = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(owner, "recover-xml-tenant-a"),
    )
    assert created.status_code == 201

    tenant_b = await _token(
        client,
        tenant_id=uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        email="b@iaerp.local",
        scopes=["tax:read"],
    )
    hidden = await client.get(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(tenant_b),
    )
    assert hidden.status_code == 200
    assert hidden.json() is None


async def test_recovery_creation_is_idempotent_and_rejects_a_second_active_job(client) -> None:
    period_id, _document_id, _key = await _seed_preliminary()
    token = await _token(client)
    first = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-stable-key"),
    )
    replay = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-stable-key"),
    )
    competing = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-other-key"),
    )
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert competing.status_code == 409
    async with SessionFactory() as session:
        jobs = list(await session.scalars(select(TaxXmlRecoveryJob)))
    assert len(jobs) == 1


async def test_large_job_uses_normalized_items_without_a_thousand_document_cutoff(client) -> None:
    async with SessionFactory() as session, session.begin():
        await session.execute(update(Tenant).where(Tenant.id == TENANT_A).values(ruc=RECEIVER_RUC))
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2025,
            month=11,
            obligation_type="IVA",
            status="EVIDENCIA_INCOMPLETA",
        )
        session.add(period)
        await session.flush()
        session.add_all(
            [
                FiscalDocument(
                    tenant_id=TENANT_A,
                    tax_period_id=period.id,
                    direction="RECIBIDO",
                    doc_type="FACTURA",
                    access_key=_valid_key_for_sequence(sequence),
                    issue_date=date(2025, 11, 11),
                    counterparty_identification=ISSUER_RUC,
                    subtotal=Decimal("1.00"),
                    tax_total=Decimal("0.15"),
                    total=Decimal("1.15"),
                    is_preliminary=True,
                )
                for sequence in range(1, 1202)
            ]
        )
        await session.flush()
        period_id = period.id

    token = await _token(client)
    response = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-large-normalized-job"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["totalCount"] == 1201
    assert response.json()["items"] == []
    job_id = uuid.UUID(response.json()["id"])
    async with SessionFactory() as session:
        item_count = len(
            list(
                await session.scalars(
                    select(TaxXmlRecoveryItem.id).where(TaxXmlRecoveryItem.job_id == job_id)
                )
            )
        )
    assert item_count == 1201


async def test_technical_failure_is_requeued_for_worker_retry(client, monkeypatch) -> None:
    period_id, _document_id, _key = await _seed_preliminary()
    token = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-technical-retry"),
    )
    job_id = uuid.UUID(created.json()["id"])

    class FailingSRIClient(FakeSRIClient):
        async def check_authorization(self, access_key: str) -> AuthorizationResult:
            self.calls += 1
            raise RuntimeError("temporary SRI outage")

    failing = FailingSRIClient(b"")
    monkeypatch.setattr(recovery_worker, "_default_client", lambda: failing)
    monkeypatch.setattr(recovery_worker.asyncio, "sleep", lambda _seconds: _noop())
    message = OutboxMessage(
        event_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        event_type="tax.xml_recovery.requested",
        aggregate_type="tax_xml_recovery_job",
        aggregate_id=str(job_id),
        payload={},
        correlation_id=str(uuid.uuid4()),
        attempts=1,
    )
    with pytest.raises(RuntimeError, match="temporary SRI outage"):
        await recovery_worker.handle_recovery_requested(message)
    async with SessionFactory() as session:
        job = await session.get(TaxXmlRecoveryJob, job_id)
        item = await session.scalar(
            select(TaxXmlRecoveryItem).where(TaxXmlRecoveryItem.job_id == job_id)
        )
    assert failing.calls == 3
    assert job is not None and job.status == "QUEUED"
    assert job.processed_count == 0
    assert item is not None and item.status == "PENDING"


async def _noop() -> None:
    return None


async def test_active_lease_blocks_duplicate_delivery(client) -> None:
    period_id, _document_id, key = await _seed_preliminary()
    token = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-xml-active-lease"),
    )
    job_id = uuid.UUID(created.json()["id"])
    fake = FakeSRIClient(_authorized_xml(key))
    async with SessionFactory() as session, session.begin():
        job = await session.get(TaxXmlRecoveryJob, job_id)
        assert job is not None
        job.status = "RUNNING"
        job.lease_until = (
            recovery_worker.datetime.now(recovery_worker.UTC) + recovery_worker.LEASE_DURATION
        )
    with pytest.raises(RecoveryAlreadyRunningError):
        await run_recovery_job(job_id, sri_client=fake)
    assert fake.calls == 0


async def test_credit_note_recovery_reduces_the_linked_payable(client, monkeypatch) -> None:
    period_id, note_id, payable_id, key = await _seed_preliminary_credit_note()

    async def fake_upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        return None

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", fake_upload)
    token = await _token(client)
    created = await client.post(
        f"/api/v1/tax/periods/{period_id}/xml-recovery",
        headers=_auth(token, "recover-credit-note-xml"),
    )
    await run_recovery_job(
        uuid.UUID(created.json()["id"]),
        sri_client=FakeSRIClient(_authorized_credit_note_xml(key)),
    )
    async with SessionFactory() as session:
        note = await session.get(FiscalDocument, note_id)
        payable = await session.get(Payable, payable_id)
        movements = list(
            await session.scalars(
                select(PayableMovement).where(PayableMovement.payable_id == payable_id)
            )
        )
    assert note is not None and note.is_preliminary is False
    assert note.related_access_key == _valid_key()
    assert payable is not None and payable.status == "PARTIALLY_PAID"
    assert len(movements) == 1 and movements[0].amount == Decimal("5.75")

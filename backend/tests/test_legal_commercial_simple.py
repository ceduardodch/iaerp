import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.db.session import SessionFactory
from app.models.billing import DocumentArtifact, SalesDocument
from app.models.legal_commercial import (
    AwsConsumptionCut,
    BillingProposal,
    CommercialContract,
    ContractVersion,
)
from app.models.masters import EmissionPoint, Establishment, Party, Product, TaxCategory
from app.models.receivables import CollectionPolicy, Receivable, ReceivableInstallment
from app.schemas.legal_commercial import CommercialContractCreate, ContractBillingPrepare
from app.services import billing, crm_integrations, legal_commercial, storage
from app.workers.collections import schedule_receivable_reminders
from tests.conftest import TENANT_A, TENANT_B, USER_A, USER_B


def _context(tenant_id: uuid.UUID = TENANT_A, actor_id: uuid.UUID = USER_A) -> AuthContext:
    return AuthContext(
        actor_id=str(actor_id),
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset({"owner"}),
        scopes=frozenset({"commercial:read", "commercial:write", "invoices:write"}),
        token_id="contract-tests",
    )


def _pdf(*, signed: bool = False) -> bytes:
    signature = (
        b"/Type /Sig /ByteRange [0 10 20 30] /SubFilter /adbe.pkcs7.detached" if signed else b""
    )
    return b"%PDF-1.4\n1 0 obj\n" + signature + b"\nendobj\n%%EOF"


async def _customer(session, *, tenant_id: uuid.UUID, suffix: str) -> Party:
    party = Party(
        tenant_id=tenant_id,
        name=f"Cliente {suffix}",
        identification_type="RUC",
        identification_number=f"179{suffix.zfill(10)}"[:13],
        roles=["CUSTOMER"],
        email=f"{suffix.lower()}@example.com",
        active=True,
    )
    session.add(party)
    await session.flush()
    return party


async def _billing_masters(
    session, *, suffix: str
) -> tuple[Party, Establishment, EmissionPoint, Product, TaxCategory]:
    party = await _customer(session, tenant_id=TENANT_A, suffix=suffix)
    tax = await session.scalar(select(TaxCategory).where(TaxCategory.tenant_id == TENANT_A))
    assert tax is not None
    establishment = Establishment(
        tenant_id=TENANT_A,
        code=suffix[-3:].zfill(3),
        name=f"Matriz {suffix}",
        address="Quito",
        active=True,
    )
    session.add(establishment)
    await session.flush()
    point = EmissionPoint(
        tenant_id=TENANT_A,
        establishment_id=establishment.id,
        code="001",
        active=True,
    )
    product = Product(
        tenant_id=TENANT_A,
        name=f"Servicio {suffix}",
        code=f"S-{suffix}",
        unit_price=Decimal("1.000000"),
        tax_category_id=tax.id,
        active=True,
    )
    session.add_all([point, product])
    await session.flush()
    return party, establishment, point, product, tax


def test_pdf_without_signature_is_not_accepted_as_signed() -> None:
    status, details = legal_commercial.technical_signature_precheck(_pdf())
    assert status == "SIGNATURE_NOT_FOUND"
    assert details["signature_count"] == 0


def test_streamone_evidence_rejects_an_unexpected_file_type() -> None:
    with pytest.raises(HTTPException, match="CSV, XLS, XLSX or PDF"):
        legal_commercial._validate_aws_report("reporte.exe", b"not-a-report")


async def test_tenant_isolation_and_sent_version_immutability(monkeypatch) -> None:
    async def fake_upload(*, object_key: str, data: bytes, content_type: str):
        return storage.UploadResult(object_key=object_key, sha256="a" * 64, size_bytes=len(data))

    monkeypatch.setattr(storage, "upload_private_object", fake_upload)
    async with SessionFactory() as session, session.begin():
        party = await _customer(session, tenant_id=TENANT_A, suffix="101")
        contract = await legal_commercial.create_contract(
            session,
            _context(),
            CommercialContractCreate(
                party_id=party.id,
                contract_number="CT-IMMUTABLE",
                title="Contrato inmutable",
                service_type="ONE_OFF",
            ),
        )
        version = ContractVersion(
            tenant_id=TENANT_A,
            contract_id=contract.id,
            version_number=1,
            status="DRAFT",
            valid_from=today_in_fiscal_timezone(),
            payment_terms_days=0,
            pricing_rules=[],
        )
        session.add(version)
        await session.flush()
        await legal_commercial.upload_sent_contract(
            session,
            _context(),
            contract_id=contract.id,
            version_id=version.id,
            filename="contrato.pdf",
            data=_pdf(),
        )
        with pytest.raises(HTTPException, match="immutable"):
            await legal_commercial.upload_sent_contract(
                session,
                _context(),
                contract_id=contract.id,
                version_id=version.id,
                filename="otro.pdf",
                data=_pdf(),
            )
        signed = await legal_commercial.upload_signed_contract(
            session,
            _context(),
            contract_id=contract.id,
            version_id=version.id,
            filename="firmado.pdf",
            data=_pdf(signed=True),
        )
        assert signed.status == "PENDING_SIGNATURE"
        assert signed.signature_precheck_status == "SIGNATURE_FOUND"
        with pytest.raises(HTTPException, match="immutable"):
            await legal_commercial.upload_signed_contract(
                session,
                _context(),
                contract_id=contract.id,
                version_id=version.id,
                filename="reemplazo.pdf",
                data=_pdf(signed=True),
            )
        assert await legal_commercial.list_contracts(session, _context(TENANT_B, USER_B)) == []


async def test_duplicate_gmail_reply_is_ignored(monkeypatch) -> None:
    async with SessionFactory() as session, session.begin():
        party = await _customer(session, tenant_id=TENANT_A, suffix="102")
        contract = CommercialContract(
            tenant_id=TENANT_A,
            party_id=party.id,
            contract_number="CT-GMAIL",
            title="Contrato Gmail",
            service_type="ONE_OFF",
            status="PENDING_SIGNATURE",
        )
        session.add(contract)
        await session.flush()
        version = ContractVersion(
            tenant_id=TENANT_A,
            contract_id=contract.id,
            version_number=1,
            status="PENDING_SIGNATURE",
            valid_from=today_in_fiscal_timezone(),
            payment_terms_days=0,
            pricing_rules=[],
            gmail_message_id="sent-1",
            gmail_thread_id="thread-1",
            reply_message_id="reply-1",
            signed_artifact_object_key="private/signed.pdf",
            signed_artifact_sha256="b" * 64,
        )
        session.add(version)
        await session.flush()

        async def fake_thread(*args, **kwargs):
            return 2, [("sent-1", "sender@example.com"), ("reply-1", party.email)], []

        monkeypatch.setattr(crm_integrations, "google_thread_pdfs", fake_thread)
        result = await legal_commercial.sync_contract_email(
            session,
            _context(),
            contract_id=contract.id,
            version_id=version.id,
        )
        assert result.reply_detected is True
        assert result.duplicate_ignored is True
        assert result.signed_pdf_received is False


async def test_expired_contract_cannot_be_activated() -> None:
    async with SessionFactory() as session, session.begin():
        party = await _customer(session, tenant_id=TENANT_A, suffix="103")
        contract = CommercialContract(
            tenant_id=TENANT_A,
            party_id=party.id,
            contract_number="CT-EXPIRED",
            title="Contrato vencido",
            service_type="ONE_OFF",
            status="SIGNED",
        )
        session.add(contract)
        await session.flush()
        version = ContractVersion(
            tenant_id=TENANT_A,
            contract_id=contract.id,
            version_number=1,
            status="SIGNED",
            valid_from=today_in_fiscal_timezone() - timedelta(days=20),
            valid_to=today_in_fiscal_timezone() - timedelta(days=1),
            payment_terms_days=0,
            pricing_rules=[],
            signed_artifact_object_key="private/signed.pdf",
            firmaec_confirmed_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        with pytest.raises(HTTPException, match="expired"):
            await legal_commercial.activate_contract(
                session,
                _context(),
                contract_id=contract.id,
                version_id=version.id,
            )


@pytest.mark.parametrize(
    ("service_type", "amount_fields", "expected"),
    [
        ("FIXED_MONTHLY", {"amount": "250.00"}, Decimal("250.00")),
        (
            "MILESTONE",
            {"baseAmount": "1000.00", "percentage": "40.00"},
            Decimal("400.00"),
        ),
    ],
)
async def test_fixed_and_milestone_billing_are_prepared(
    service_type: str,
    amount_fields: dict[str, str],
    expected: Decimal,
) -> None:
    async with SessionFactory() as session, session.begin():
        suffix = "201" if service_type == "FIXED_MONTHLY" else "202"
        party, establishment, point, product, tax = await _billing_masters(session, suffix=suffix)
        rule = {
            "establishmentId": str(establishment.id),
            "emissionPointId": str(point.id),
            "productId": str(product.id),
            "taxCode": tax.sri_code,
            "description": "Servicio mensual",
            **amount_fields,
        }
        rules = [rule]
        if service_type == "MILESTONE":
            rules.extend(
                [
                    {**rule, "percentage": "20.00"},
                    {**rule, "percentage": "40.00"},
                ]
            )
        contract = CommercialContract(
            tenant_id=TENANT_A,
            party_id=party.id,
            contract_number=f"CT-{suffix}",
            title="Servicio mensual",
            service_type=service_type,
            status="ACTIVE",
            report_required=False,
            collection_enabled=True,
        )
        session.add(contract)
        await session.flush()
        version = ContractVersion(
            tenant_id=TENANT_A,
            contract_id=contract.id,
            version_number=1,
            status="ACTIVE",
            valid_from=today_in_fiscal_timezone() - timedelta(days=1),
            valid_to=today_in_fiscal_timezone() + timedelta(days=90),
            payment_terms_days=30,
            pricing_rules=rules,
        )
        session.add(version)
        await session.flush()
        contract.current_version_id = version.id
        proposal = await legal_commercial.prepare_contract_billing(
            session,
            _context(),
            contract_id=contract.id,
            data=ContractBillingPrepare(
                period_start=today_in_fiscal_timezone(),
                period_end=today_in_fiscal_timezone(),
            ),
        )
        assert proposal.total_amount == expected
        assert proposal.status == "READY_FOR_REVIEW"
        assert proposal.collection_enabled is True
        if service_type == "MILESTONE":
            second = await legal_commercial.prepare_contract_billing(
                session,
                _context(),
                contract_id=contract.id,
                data=ContractBillingPrepare(
                    period_start=today_in_fiscal_timezone(),
                    period_end=today_in_fiscal_timezone(),
                    pricing_rule_index=1,
                ),
            )
            third = await legal_commercial.prepare_contract_billing(
                session,
                _context(),
                contract_id=contract.id,
                data=ContractBillingPrepare(
                    period_start=today_in_fiscal_timezone(),
                    period_end=today_in_fiscal_timezone(),
                    pricing_rule_index=2,
                ),
            )
            assert (proposal.total_amount, second.total_amount, third.total_amount) == (
                Decimal("400.00"),
                Decimal("200.00"),
                Decimal("400.00"),
            )


async def test_aws_billing_requires_reviewed_cut_and_matching_manual_total() -> None:
    async with SessionFactory() as session, session.begin():
        party, establishment, point, product, tax = await _billing_masters(session, suffix="203")
        rule = {
            "establishmentId": str(establishment.id),
            "emissionPointId": str(point.id),
            "productId": str(product.id),
            "taxCode": tax.sri_code,
            "description": "Consumo AWS",
        }
        contract = CommercialContract(
            tenant_id=TENANT_A,
            party_id=party.id,
            contract_number="CT-AWS-203",
            title="AWS",
            service_type="AWS_MONTHLY",
            status="ACTIVE",
            report_required=True,
            collection_enabled=True,
        )
        session.add(contract)
        await session.flush()
        version = ContractVersion(
            tenant_id=TENANT_A,
            contract_id=contract.id,
            version_number=1,
            status="ACTIVE",
            valid_from=today_in_fiscal_timezone() - timedelta(days=1),
            valid_to=today_in_fiscal_timezone() + timedelta(days=90),
            payment_terms_days=30,
            pricing_rules=[rule],
        )
        cut = AwsConsumptionCut(
            tenant_id=TENANT_A,
            party_id=party.id,
            period_start=today_in_fiscal_timezone(),
            period_end=today_in_fiscal_timezone(),
            source="XLSX_UPLOAD",
            status="REVIEWED",
            currency="USD",
            total_cost=Decimal("123.45"),
            evidence_object_key="private/streamone.xlsx",
        )
        session.add_all([version, cut])
        await session.flush()
        contract.current_version_id = version.id
        proposal = await legal_commercial.prepare_contract_billing(
            session,
            _context(),
            contract_id=contract.id,
            data=ContractBillingPrepare(
                period_start=cut.period_start,
                period_end=cut.period_end,
                aws_consumption_cut_id=cut.id,
                manual_total=Decimal("123.45"),
            ),
        )
        assert proposal.total_amount == Decimal("123.45")
        assert proposal.report_required is True


async def test_required_report_blocks_invoice_email() -> None:
    async with SessionFactory() as session, session.begin():
        party, establishment, point, _, _ = await _billing_masters(session, suffix="204")
        document = SalesDocument(
            tenant_id=TENANT_A,
            document_type="INVOICE",
            establishment_id=establishment.id,
            emission_point_id=point.id,
            sequential="000000001",
            party_id=party.id,
            issue_date=today_in_fiscal_timezone(),
            status="AUTHORIZED",
            currency="USD",
            subtotal=Decimal("100.00"),
            tax_total=Decimal("15.00"),
            total=Decimal("115.00"),
            fiscal_policy_version="test",
        )
        session.add(document)
        await session.flush()
        session.add_all(
            [
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=document.id,
                    artifact_type="xml-signed",
                    object_key="private/invoice.xml",
                    sha256="a" * 64,
                    version=1,
                ),
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=document.id,
                    artifact_type="ride-pdf",
                    object_key="private/ride.pdf",
                    sha256="b" * 64,
                    version=1,
                ),
                BillingProposal(
                    tenant_id=TENANT_A,
                    party_id=party.id,
                    sales_document_id=document.id,
                    issue_date=document.issue_date,
                    billing_type="FIXED_MONTHLY",
                    status="CONVERTED",
                    currency="USD",
                    total_amount=Decimal("100.00"),
                    commercial_snapshot={},
                    exception_reason=None,
                    report_required=True,
                    collection_enabled=False,
                ),
            ]
        )
        await session.flush()
        with pytest.raises(HTTPException, match="monthly report"):
            await billing.preview_invoice_email(session, _context(), document.id)


async def test_collection_policy_and_invoice_opt_in_are_both_required() -> None:
    async with SessionFactory() as session, session.begin():
        party = await _customer(session, tenant_id=TENANT_A, suffix="205")
        establishment = Establishment(
            tenant_id=TENANT_A, code="205", name="Matriz", address="Quito", active=True
        )
        session.add(establishment)
        await session.flush()
        point = EmissionPoint(
            tenant_id=TENANT_A,
            establishment_id=establishment.id,
            code="001",
            active=True,
        )
        session.add(point)
        await session.flush()
        document = SalesDocument(
            tenant_id=TENANT_A,
            document_type="INVOICE",
            establishment_id=establishment.id,
            emission_point_id=point.id,
            sequential="000000002",
            party_id=party.id,
            issue_date=today_in_fiscal_timezone(),
            status="AUTHORIZED",
            currency="USD",
            subtotal=Decimal("10.00"),
            tax_total=Decimal("0.00"),
            total=Decimal("10.00"),
            fiscal_policy_version="test",
            collection_enabled=False,
        )
        session.add(document)
        await session.flush()
        receivable = Receivable(
            tenant_id=TENANT_A,
            sales_document_id=document.id,
            party_id=party.id,
            original_amount=document.total,
            currency="USD",
            status="OPEN",
            collection_enabled=False,
        )
        session.add(receivable)
        await session.flush()
        installment = ReceivableInstallment(
            tenant_id=TENANT_A,
            receivable_id=receivable.id,
            sequence=1,
            due_date=document.issue_date,
            amount=document.total,
        )
        session.add_all([installment, CollectionPolicy(tenant_id=TENANT_A, enabled=True)])
        await session.flush()
        assert (
            await schedule_receivable_reminders(
                session, receivable=receivable, installments=[installment]
            )
            == 0
        )

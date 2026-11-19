"""Production rules exercised with synthetic invoices and local fakes for every external effect."""

import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionFactory, engine
from app.integrations.sri.protocol import AuthorizationResult
from app.models.billing import (
    DocumentArtifact,
    InvoiceEmailDispatch,
    SalesDocument,
    SRITransmission,
)
from app.models.legal_commercial import BillingProposal
from app.models.platform import AuditEvent, OutboxEvent, TenantFiscalSettings
from app.services import billing, crm_integrations
from app.workers import sri_transmission
from app.workers.outbox import OutboxMessage
from tests.test_billing_api import auth, token_for
from tests.test_ios_permissions import TENANT_A, TENANT_B, claims, membership, oidc_signer
from tests.test_legal_commercial_simple import _billing_masters


@pytest_asyncio.fixture
async def delivery_case(client, monkeypatch):
    web = await token_for(client, "a@iaerp.local", TENANT_A, ["invoices:read", "invoices:write"])
    await membership(TENANT_B, ["owner"])
    async with SessionFactory() as session, session.begin():
        party, est, point, _, _ = await _billing_masters(session, suffix="902")
        key = "0" * 23 + "2" + "0" * 25
        doc = SalesDocument(
            tenant_id=TENANT_A,
            document_type="INVOICE",
            establishment_id=est.id,
            emission_point_id=point.id,
            sequential="000000001",
            party_id=party.id,
            issue_date=date(2025, 1, 1),
            status="AUTHORIZED",
            currency="USD",
            subtotal=Decimal("0.05"),
            tax_total=Decimal(0),
            total=Decimal("0.05"),
            fiscal_policy_version="synthetic",
            access_key=key,
            authorization_number=key,
        )
        session.add(doc)
        await session.flush()
        content = {"xml": b"<synthetic/>", "pdf": b"%PDF synthetic", "report": b"%PDF report"}
        for kind, path in (("xml-signed", "xml"), ("ride-pdf", "pdf")):
            session.add(
                DocumentArtifact(
                    tenant_id=TENANT_A,
                    sales_document_id=doc.id,
                    artifact_type=kind,
                    object_key=path,
                    sha256=hashlib.sha256(content[path]).hexdigest(),
                    version=1,
                )
            )
        session.add(TenantFiscalSettings(tenant_id=TENANT_A, sri_environment="2"))
        document_id = doc.id

    sign = oidc_signer(monkeypatch)
    scopes = "invoices:read invoices:write invoices:email invoices:issue"
    native = sign(claims(scope=scopes))
    foreign = sign(claims("tenant-b", scope=scopes))
    settings = get_settings()
    for k, v in {
        "APP_ENV": "production",
        "SRI_TRANSMISSION_MODE": "soap",
        "SRI_ENVIRONMENT": "2",
        "SRI_RECEPTION_URL": None,
        "SRI_AUTHORIZATION_URL": None,
    }.items():
        monkeypatch.setattr(settings, k, v)
    sent = []

    async def download(*, object_key):
        return content[object_key]

    async def sender(*args):
        return "sender@example.com"

    async def send(_session, _ctx, **mail):
        sent.append(mail)
        return "provider-id-1"

    async def not_found(*args):
        return None

    monkeypatch.setattr(billing.storage, "download_artifact", download)
    monkeypatch.setattr(crm_integrations, "prepare_google_sender", sender)
    monkeypatch.setattr(crm_integrations, "send_google_email", send)
    monkeypatch.setattr(crm_integrations, "find_sent_reference", not_found)
    return document_id, f"/api/v1/invoices/{document_id}", native, foreign, web, sent, content


async def test_review_and_single_delivery_across_clients(client, delivery_case, monkeypatch):
    doc_id, url, native, foreign, web, sent, _ = delivery_case
    assert (await client.get(url + "/delivery-status", headers=auth(foreign))).status_code == 404
    status = await client.get(url + "/delivery-status", headers=auth(native))
    assert status.json() == {
        "emailStatus": "NOT_SENT",
        "fiscalEnvironment": "PRODUCTION",
        "receipt": None,
    }
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    body = {"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]}
    for alteration in ({"recipient": "other@example.com"}, {"previewDigest": "0" * 64}):
        rejected = await client.post(
            url + "/email", headers=auth(native, str(uuid.uuid4())), json=body | alteration
        )
        assert rejected.status_code == 409 and not sent
    key = str(uuid.uuid4())
    first = await client.post(url + "/email", headers=auth(native, key), json=body)
    assert first.status_code == 200, first.text
    assert [a[0] for a in sent[0]["attachments"]] == preview["attachmentNames"]
    assert sent[0]["recipient"] == preview["recipient"] and sent[0]["subject"] == preview["subject"]
    for repeat in (key, str(uuid.uuid4())):
        replay = await client.post(url + "/email", headers=auth(native, repeat), json=body)
        assert replay.json() == first.json()
    assert len(sent) == 1
    status = (await client.get(url + "/delivery-status", headers=auth(native))).json()
    assert status["emailStatus"] == "SENT" and status["receipt"] == first.json()
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    replay = await client.post(
        url + "/email", headers=auth(web, str(uuid.uuid4())), json={"recipient": body["recipient"]}
    )
    assert replay.json() == first.json() and len(sent) == 1
    resend = await client.post(
        url + "/email",
        headers=auth(web, str(uuid.uuid4())),
        json={"recipient": body["recipient"], "resend": True},
    )
    assert resend.status_code == 200 and len(sent) == 2
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(InvoiceEmailDispatch)) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "invoice.emailed", AuditEvent.entity_id == str(doc_id))
            )
            == 2
        )


async def test_web_first_and_later_mobile_returns_original_receipt(
    client, delivery_case, monkeypatch
):
    _, url, native, _, web, sent, _ = delivery_case
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    body = {"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]}
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    first = await client.post(
        url + "/email", headers=auth(web, str(uuid.uuid4())), json={"recipient": body["recipient"]}
    )
    assert first.status_code == 200
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "oidc")
    replay = await client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    assert replay.json() == first.json() and len(sent) == 1


async def test_accepted_before_timeout_is_reconciled_without_resend(
    client, delivery_case, monkeypatch
):
    _, url, native, _, _, sent, _ = delivery_case
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    body = {"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]}

    async def accept_then_timeout(_session, _context, **mail):
        sent.append(mail)
        raise httpx.ReadTimeout("synthetic lost response")

    async def find(_session, _context, reference):
        assert reference == sent[0]["provider_reference"]
        return "recovered-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", accept_then_timeout)
    first = await client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    assert first.status_code == 409 and first.json()["detail"] == "invoice_email_pending"
    assert (await client.get(url + "/delivery-status", headers=auth(native))).json()[
        "emailStatus"
    ] == "PENDING"
    assert (
        await client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    ).status_code == 409
    monkeypatch.setattr(crm_integrations, "find_sent_reference", find)
    recovered = (await client.get(url + "/delivery-status", headers=auth(native))).json()
    assert recovered["receipt"]["messageId"] == "recovered-id" and len(sent) == 1
    replay = await client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    assert replay.json() == recovered["receipt"] and len(sent) == 1


async def test_required_report_approval_and_verified_bytes(client, delivery_case):
    doc_id, url, native, _, _, sent, content = delivery_case
    async with SessionFactory() as session, session.begin():
        doc = await session.get(SalesDocument, doc_id)
        proposal = BillingProposal(
            tenant_id=TENANT_A,
            party_id=doc.party_id,
            sales_document_id=doc_id,
            issue_date=doc.issue_date,
            billing_type="FIXED_MONTHLY",
            status="CONVERTED",
            currency="USD",
            total_amount=doc.total,
            commercial_snapshot={},
            report_required=True,
            collection_enabled=False,
        )
        session.add(proposal)
    blocked = await client.get(url + "/email-preview", headers=auth(native))
    assert blocked.status_code == 422 and "monthly report" in blocked.json()["detail"]
    async with SessionFactory() as session, session.begin():
        prop = await session.get(BillingProposal, proposal.id)
        prop.report_approved_at = datetime.now(UTC)
        prop.report_object_key = "report"
        prop.report_file_name = "Informe.pdf"
        prop.report_sha256 = hashlib.sha256(content["report"]).hexdigest()
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    assert len(preview["attachmentNames"]) == 3 and preview["attachmentNames"][-1] == "Informe.pdf"
    body = {"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]}
    original = content["report"]
    content["report"] = b"modified"
    blocked = await client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    assert blocked.status_code == 409 and not sent
    content["report"] = original
    sent_response = await client.post(
        url + "/email", headers=auth(native, str(uuid.uuid4())), json=body
    )
    assert sent_response.status_code == 200 and sent[0]["attachments"][-1][-1] == original


@pytest.mark.parametrize(
    "setting",
    ["SRI_RECEPTION_URL", "SRI_AUTHORIZATION_URL", "SRI_ENVIRONMENT", "SRI_TRANSMISSION_MODE"],
)
async def test_environment_check_on_preview_and_issue(client, delivery_case, monkeypatch, setting):
    _, url, native, _, _, sent, _ = delivery_case
    value = {"SRI_ENVIRONMENT": "1", "SRI_TRANSMISSION_MODE": "simulator"}.get(
        setting, "https://celcer.sri.gob.ec"
    )
    monkeypatch.setattr(get_settings(), setting, value)
    assert (await client.get(url + "/delivery-status", headers=auth(native))).json()[
        "fiscalEnvironment"
    ] != "PRODUCTION"
    for path, method in (("issue", "post"), ("email-preview", "get")):
        result = await getattr(client, method)(
            url + "/" + path, headers=auth(native, str(uuid.uuid4()))
        )
        assert (
            result.status_code == 409
            and result.json()["detail"] == "invoice_environment_not_production"
        )
    assert not sent


async def test_worker_after_lost_reception_only_queries_authorization(delivery_case, monkeypatch):
    ident, *_ = delivery_case
    async with SessionFactory() as session, session.begin():
        doc = await session.get(SalesDocument, ident)
        doc.status = "SIGNED"
        doc.authorization_number = None
        session.add(
            SRITransmission(
                tenant_id=TENANT_A,
                sales_document_id=ident,
                access_key=doc.access_key,
                status="PENDING",
                attempts=0,
                messages=[],
            )
        )

    class FakeSRI:
        receptions = 0
        queries = 0

        async def send_reception(self, xml, key):
            self.receptions += 1
            raise TimeoutError("Lost reply from reception")

        async def check_authorization(self, key):
            self.queries += 1
            return AuthorizationResult(status="PENDING_AUTHORIZATION")

    sri = FakeSRI()
    msg = OutboxMessage(
        uuid.uuid4(),
        TENANT_A,
        "invoice.signed",
        "sales_document",
        str(ident),
        {"native_confirmed": True},
        "synthetic",
        0,
    )

    async def execute():
        async with SessionFactory() as session, session.begin():
            await sri_transmission.handle_invoice_signed(session, msg, sri_client=sri)

    monkeypatch.setattr(get_settings(), "SRI_AUTHORIZATION_URL", "https://wrong.example.com")
    await execute()
    assert sri.receptions == sri.queries == 0
    monkeypatch.setattr(get_settings(), "SRI_AUTHORIZATION_URL", None)
    await execute()
    await execute()
    assert sri.receptions == sri.queries == 1
    async with SessionFactory() as session:
        updated = await session.get(SalesDocument, ident)
        assert updated.status == "PENDING_AUTHORIZATION"


@pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Concurrent tenant row locks require PostgreSQL"
)
async def test_api_concurrent_confirmations_call_provider_once(client, delivery_case, monkeypatch):
    _, url, native, _, _, sent, _ = delivery_case
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    body = {"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]}
    started, finish = asyncio.Event(), asyncio.Event()

    async def accepting(_session, _ctx, **mail):
        sent.append(mail)
        started.set()
        await asyncio.wait_for(finish.wait(), 5)
        return "once"

    monkeypatch.setattr(crm_integrations, "send_google_email", accepting)
    task = asyncio.create_task(
        client.post(url + "/email", headers=auth(native, str(uuid.uuid4())), json=body)
    )
    await asyncio.wait_for(started.wait(), 5)
    try:
        second = await client.post(
            url + "/email", headers=auth(native, str(uuid.uuid4())), json=body
        )
        assert second.status_code == 409 and second.json()["detail"] == "invoice_email_pending"
    finally:
        finish.set()
    assert (await task).status_code == 200 and len(sent) == 1


async def test_web_acceptance_with_lost_response_blocks_mobile_retry(
    client, delivery_case, monkeypatch
):
    _, url, native, _, web, sent, _ = delivery_case
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()

    async def lose_reply(_s, _ctx, **mail):
        sent.append(mail)
        raise httpx.ReadTimeout("simulated")

    monkeypatch.setattr(crm_integrations, "send_google_email", lose_reply)
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    body = {"recipient": preview["recipient"]}
    result = await client.post(url + "/email", headers=auth(web, str(uuid.uuid4())), json=body)
    assert result.status_code == 409
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "oidc")
    assert (await client.get(url + "/delivery-status", headers=auth(native))).json()[
        "emailStatus"
    ] == "PENDING"
    result = await client.post(
        url + "/email",
        headers=auth(native, str(uuid.uuid4())),
        json={**body, "previewDigest": preview["previewDigest"]},
    )
    assert (
        result.status_code == 409
        and result.json()["detail"] == "invoice_email_pending"
        and len(sent) == 1
    )


async def test_native_draft_issue_authorization_and_email_cycle(client, delivery_case, monkeypatch):
    from app.integrations.sri.protocol import ReceptionResult
    from app.models.masters import Product
    from app.models.receivables import Receivable
    from app.services.storage import UploadResult
    from app.workers.receivables import handle_invoice_authorized
    from tests.test_billing_api import _invoice_payload
    from tests.test_signing import _p12_with_trust_chain

    other_id, _, native, _, _, sent, content = delivery_case
    async with SessionFactory() as session, session.begin():
        other = await session.get(SalesDocument, other_id)
        other.sequential = "000000999"
        product = await session.scalar(select(Product).where(Product.tenant_id == TENANT_A))
        masters = {
            "party_id": str(other.party_id),
            "establishment_id": str(other.establishment_id),
            "emission_point_id": str(other.emission_point_id),
            "product_id": str(product.id),
            "tax_code": "4",
        }
        fiscal = await session.get(TenantFiscalSettings, TENANT_A)
        fiscal.certificate_object_key = "synthetic.p12"
        fiscal.certificate_password_encrypted = str(uuid.uuid4())

    password = b"synthetic"
    certificate = _p12_with_trust_chain(password)

    async def credentials(session, tid):
        return certificate, password, await session.get(TenantFiscalSettings, tid)

    async def upload(*, data, **identity):
        object_key = billing.storage.object_key_for_artifact(**identity)
        content[object_key] = data
        return UploadResult(object_key, hashlib.sha256(data).hexdigest(), len(data))

    monkeypatch.setattr(billing.fiscal_settings, "load_tenant_signing_credentials", credentials)
    monkeypatch.setattr(billing.storage, "upload_artifact", upload)
    payload = _invoice_payload(masters)
    payload["lines"][0].update(quantity="1", unitPrice="0.04")
    payload["installments"][0]["amount"] = "0.05"
    draft = await client.post(
        "/api/v1/invoices", headers=auth(native, str(uuid.uuid4())), json=payload
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["total"] == "0.05"
    identifier = draft.json()["id"]
    url = "/api/v1/invoices/" + identifier
    key = str(uuid.uuid4())
    denied_before_authorization = await client.get(url + "/email-preview", headers=auth(native))
    assert denied_before_authorization.status_code == 422
    issued = await client.post(url + "/issue", headers=auth(native, key))
    assert issued.status_code == 202, issued.text
    assert (await client.post(url + "/issue", headers=auth(native, key))).json() == issued.json()
    assert (
        await client.post(url + "/issue", headers=auth(native, str(uuid.uuid4())))
    ).status_code == 409
    signed = (await client.get(url, headers=auth(native))).json()
    assert signed["status"] == "SIGNED" and signed["accessKey"][23] == "2"

    class FiscalService:
        receptions = 0
        queries = 0

        async def send_reception(self, xml, access):
            assert access == signed["accessKey"] and b"SignatureValue" in xml
            self.receptions += 1
            return ReceptionResult(status="RECEIVED")

        async def check_authorization(self, access):
            self.queries += 1
            # A crossed authorization must not authorize or publish receivables.
            number = "1" * 49 if self.queries == 1 else access
            return AuthorizationResult(
                status="AUTHORIZED", authorization_number=number, authorized_at=datetime.now(UTC)
            )

    async def event(topic):
        async with SessionFactory() as session:
            records = (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id == identifier, OutboxEvent.event_type == topic)
                    .order_by(OutboxEvent.created_at)
                )
            ).all()
            assert len(records) == 1
            row = records[0]
            return OutboxMessage(
                row.id,
                row.tenant_id,
                row.event_type,
                row.aggregate_type,
                row.aggregate_id,
                row.payload,
                row.correlation_id,
                0,
            )

    service = FiscalService()
    message = await event("invoice.signed")
    assert message.payload["native_confirmed"] is True
    async with SessionFactory() as session, session.begin():
        await sri_transmission.handle_invoice_signed(session, message, sri_client=service)
    assert (await client.get(url, headers=auth(native))).json()["status"] != "AUTHORIZED"
    for _ in range(2):
        async with SessionFactory() as session, session.begin():
            await sri_transmission.handle_invoice_signed(session, message, sri_client=service)
    assert service.receptions == 1 and service.queries == 2
    authorized = (await client.get(url, headers=auth(native))).json()
    assert (
        authorized["authorizationNumber"] == authorized["accessKey"]
        and authorized["status"] == "AUTHORIZED"
    )
    authorized_event = await event("invoice.authorized")
    for _ in range(2):
        async with SessionFactory() as session, session.begin():
            await handle_invoice_authorized(session, authorized_event)
    async with SessionFactory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Receivable)
                .where(Receivable.sales_document_id == uuid.UUID(identifier))
            )
            == 1
        )
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    mailed = await client.post(
        url + "/email",
        headers=auth(native, str(uuid.uuid4())),
        json={"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]},
    )
    assert mailed.status_code == 200 and len(sent) == 1
    assert b"SignatureValue" in sent[0]["attachments"][0][-1]
    assert sent[0]["attachments"][1][-1].startswith(b"%PDF")


async def test_revoked_membership_while_waiting_for_lock_blocks_native_send(
    client, delivery_case, monkeypatch
):
    from app.services import invoice_delivery

    _, url, native, _, _, sent, _ = delivery_case
    preview = (await client.get(url + "/email-preview", headers=auth(native))).json()
    original_lock = invoice_delivery._lock_tenant

    async def revoke_then_lock(session, context):
        await membership(TENANT_A, ["viewer"])
        await original_lock(session, context)

    monkeypatch.setattr(invoice_delivery, "_lock_tenant", revoke_then_lock)
    result = await client.post(
        url + "/email",
        headers=auth(native, str(uuid.uuid4())),
        json={"recipient": preview["recipient"], "previewDigest": preview["previewDigest"]},
    )
    assert result.status_code == 403 and not sent
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(InvoiceEmailDispatch)) == 0


async def test_web_disconnected_gmail_remains_retryable(client, delivery_case, monkeypatch):
    from fastapi import HTTPException

    _, url, _, _, web, sent, _ = delivery_case
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    saved_send = crm_integrations.send_google_email

    async def disconnected(session, context):
        raise HTTPException(422, "Google Workspace is not connected")

    async def real_sender(session, context, **mail):
        return (
            await crm_integrations.send_google_email_with_thread(session, context, **mail)
        ).message_id

    body = {"recipient": "alternate@example.com"}
    key = str(uuid.uuid4())
    monkeypatch.setattr(crm_integrations, "_google_access_token", disconnected)
    monkeypatch.setattr(crm_integrations, "send_google_email", real_sender)
    rejected = await client.post(url + "/email", headers=auth(web, key), json=body)
    assert (
        rejected.status_code == 422
        and rejected.json()["detail"] == "Google Workspace is not connected"
    )
    assert (await client.get(url + "/delivery-status", headers=auth(web))).json()[
        "emailStatus"
    ] == "NOT_SENT"
    monkeypatch.setattr(crm_integrations, "send_google_email", saved_send)
    assert (
        await client.post(url + "/email", headers=auth(web, key), json=body)
    ).status_code == 200 and len(sent) == 1
    for address, state in ((body["recipient"], "SENT"), ("another@example.com", "NOT_SENT")):
        hashed = hashlib.sha256(address.encode()).hexdigest()
        assert (
            await client.get(
                url + "/delivery-status", params={"recipientHash": hashed}, headers=auth(web)
            )
        ).json()["emailStatus"] == state


async def test_reconciled_alternate_address_never_confirms_catalog_delivery(
    client, delivery_case, monkeypatch
):
    _, url, native, _, web, _, _ = delivery_case

    async def lose_reply(*args, **kwargs):
        raise httpx.ReadTimeout("synthetic")

    async def find(*args):
        return "alternate-gmail-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", lose_reply)
    monkeypatch.setattr(crm_integrations, "find_sent_reference", find)
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    result = await client.post(
        url + "/email",
        headers=auth(web, str(uuid.uuid4())),
        json={"recipient": "billing@example.com"},
    )
    assert result.status_code == 409
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "oidc")
    status = (await client.get(url + "/delivery-status", headers=auth(native))).json()
    assert status["emailStatus"] == "NOT_SENT" and status["receipt"] is None
    monkeypatch.setattr(get_settings(), "AUTH_MODE", "dev")
    latest = (await client.get(url + "/delivery-status", headers=auth(web))).json()
    assert (
        latest["emailStatus"] == "SENT" and latest["receipt"]["recipient"] == "billing@example.com"
    )

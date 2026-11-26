"""MCP delivery uses tenant identity, catalog recipient and a durable single dispatch."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.billing import InvoiceEmailDispatch, SalesDocument
from app.models.legal_commercial import BillingProposal
from app.models.masters import Party
from app.models.platform import AuditEvent, AutomationSettings, IdempotencyRecord
from app.services import crm_integrations, invoice_delivery
from app.services.unit_of_work import canonical_hash
from tests.test_ios_invoice_delivery import delivery_case  # noqa: F401
from tests.test_ios_permissions import TENANT_A, TENANT_B, claims, membership, oidc_signer
from tests.test_mcp_invoices import mcp_lifespan, mcp_session


async def test_mcp_registered_invoice_email(client, delivery_case, monkeypatch):  # noqa: F811
    document_id, _, _, _, _, sent, content = delivery_case
    sign = oidc_signer(monkeypatch)

    def token(scope="invoices:email", org="tenant-a"):
        return sign(
            claims(
                org, aud=get_settings().OIDC_MCP_AUDIENCE, azp="iaerp-grok-informes", scope=scope
            )
        )

    params = {"invoiceId": str(document_id), "idempotencyKey": str(uuid.uuid4())}
    async with mcp_lifespan():
        async with mcp_session(token("context:read")) as session:
            assert "invoices.email" not in {t.name for t in (await session.list_tools()).tools}
            denied = await session.call_tool("invoices.email", params)
            assert denied.isError and "invoices:email" in denied.content[0].text

        async with mcp_session(token()) as session:
            tool = next(t for t in (await session.list_tools()).tools if t.name == "invoices.email")
            assert set(tool.inputSchema["properties"]) == {"invoiceId", "idempotencyKey"}
            assert tool.inputSchema["additionalProperties"] is False
            denied = await session.call_tool("invoices.email", params)
            assert denied.isError and "disabled" in denied.content[0].text

        async with SessionFactory() as db, db.begin():
            for tenant in (TENANT_A, TENANT_B):
                (await db.get(AutomationSettings, tenant)).writes_enabled = True
        async with mcp_session(token(org="tenant-b")) as session:
            denied = await session.call_tool("invoices.email", params)
            assert denied.isError and "not found" in denied.content[0].text.lower()
        async with mcp_session(token()) as session:
            for extension in [{"recipient": "other@example.com"}, {"tenantId": str(TENANT_B)}]:
                assert (await session.call_tool("invoices.email", params | extension)).isError
            await membership(TENANT_A, ["viewer"])
            denied = await session.call_tool("invoices.email", params)
            assert denied.isError
            await membership(TENANT_A, ["billing"])
            assert not sent
            first = await session.call_tool("invoices.email", params)
            assert not first.isError, first.content

            async def unexpected_scan(*args, **kwargs):
                raise AssertionError("A confirmed dispatch must skip the legacy receipt scan")

            monkeypatch.setattr(AsyncSession, "stream", unexpected_scan)
            for key in (params["idempotencyKey"], str(uuid.uuid4())):
                replay = await session.call_tool("invoices.email", params | {"idempotencyKey": key})
                assert replay.structuredContent == first.structuredContent
            async with SessionFactory() as db, db.begin():
                doc = await db.get(SalesDocument, document_id)
                (await db.get(Party, doc.party_id)).email = "new@example.com"
            denied = await session.call_tool(
                "invoices.email", params | {"idempotencyKey": str(uuid.uuid4())}
            )
            assert denied.isError and "different address" in denied.content[0].text
    assert len(sent) == 1 and sent[0]["recipient"] == "902@example.com"
    assert [(mime, data) for _, mime, data in sent[0]["attachments"]] == [
        ("application/xml", content["xml"]),
        ("application/pdf", content["pdf"]),
    ]
    async with SessionFactory() as db:
        assert await db.scalar(select(func.count()).select_from(InvoiceEmailDispatch)) == 1
        assert set(
            await db.scalars(
                select(AuditEvent.action).where(AuditEvent.entity_id == str(document_id))
            )
        ) >= {"invoice.email_requested", "invoice.emailed"}


async def test_mcp_blocks_extra_report_and_unauthorized_document(
    client,
    delivery_case,  # noqa: F811
    monkeypatch,
):
    document_id, _, _, _, _, sent, _ = delivery_case
    sign = oidc_signer(monkeypatch)
    token = sign(
        claims(
            aud=get_settings().OIDC_MCP_AUDIENCE, azp="iaerp-grok-informes", scope="invoices:email"
        )
    )
    params = {"invoiceId": str(document_id), "idempotencyKey": str(uuid.uuid4())}
    async with SessionFactory() as db, db.begin():
        (await db.get(AutomationSettings, TENANT_A)).writes_enabled = True
        (await db.get(SalesDocument, document_id)).status = "DRAFT"
    async with mcp_lifespan(), mcp_session(token) as session:
        denied = await session.call_tool("invoices.email", params)
        assert denied.isError and "authorized" in denied.content[0].text
        async with SessionFactory() as db, db.begin():
            doc = await db.get(SalesDocument, document_id)
            doc.status = "AUTHORIZED"
            db.add(
                BillingProposal(
                    tenant_id=TENANT_A,
                    party_id=doc.party_id,
                    sales_document_id=doc.id,
                    issue_date=doc.issue_date,
                    billing_type="FIXED_MONTHLY",
                    status="CONVERTED",
                    currency="USD",
                    total_amount=doc.total,
                    commercial_snapshot={},
                    report_required=True,
                    collection_enabled=False,
                    report_approved_at=datetime.now(UTC),
                    report_object_key="report",
                    report_sha256="0" * 64,
                )
            )
        denied = await session.call_tool("invoices.email", params)
        assert denied.isError and "separate delivery" in denied.content[0].text
    assert not sent


async def test_mcp_recovers_provider_receipt_without_sending_again(
    client,
    delivery_case,  # noqa: F811
    monkeypatch,
):
    document_id, _, _, _, _, sent, _ = delivery_case
    sign = oidc_signer(monkeypatch)
    token = sign(
        claims(
            aud=get_settings().OIDC_MCP_AUDIENCE, azp="iaerp-grok-informes", scope="invoices:email"
        )
    )
    params = {"invoiceId": str(document_id), "idempotencyKey": str(uuid.uuid4())}
    async with SessionFactory() as db, db.begin():
        (await db.get(AutomationSettings, TENANT_A)).writes_enabled = True

    async def timeout(_session, _ctx, **mail):
        sent.append(mail)
        raise httpx.ReadTimeout("synthetic lost reply")

    async def find(_session, _ctx, reference):
        assert reference == sent[0]["provider_reference"]
        return "recovered-id"

    monkeypatch.setattr(crm_integrations, "send_google_email", timeout)
    async with mcp_lifespan(), mcp_session(token) as session:
        pending = await session.call_tool("invoices.email", params)
        assert pending.isError and "invoice_email_pending" in pending.content[0].text
        monkeypatch.setattr(crm_integrations, "find_sent_reference", find)
        recovered = await session.call_tool("invoices.email", params)
        assert not recovered.isError and recovered.structuredContent["messageId"] == "recovered-id"
        assert len(sent) == 1


async def test_mcp_recognizes_delivery_before_dispatch_migration(
    client,
    delivery_case,  # noqa: F811
    monkeypatch,
):
    document_id, _, _, _, _, sent, _ = delivery_case
    sign = oidc_signer(monkeypatch)
    token = sign(
        claims(
            aud=get_settings().OIDC_MCP_AUDIENCE, azp="iaerp-grok-informes", scope="invoices:email"
        )
    )
    async with SessionFactory() as db, db.begin():
        doc = await db.get(SalesDocument, document_id)
        (await db.get(Party, doc.party_id)).email = "updated@example.com"
        (await db.get(AutomationSettings, TENANT_A)).writes_enabled = True
        old_recipient = "previous@example.com"
        db.add(
            IdempotencyRecord(
                tenant_id=TENANT_A,
                actor_id="prior-actor",
                operation="invoices.email",
                idempotency_key=str(uuid.uuid4()),
                status="COMPLETED",
                request_hash=canonical_hash(
                    {"invoice_id": str(document_id), "recipient": old_recipient}
                ),
                response_body={
                    "recipient": old_recipient, "messageId": "old-google-id",
                    "senderAddress": "billing@example.com", "senderName": "Synthetic",
                    "attachmentNames": ["invoice.xml", "invoice.pdf"],
                },
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    async with mcp_lifespan(), mcp_session(token) as session:
        observed = []
        original_stream = AsyncSession.stream
        original_lock = invoice_delivery._lock_tenant

        async def observe_stream(db, *args, **kwargs):
            observed.append(("scan", db.sync_session.get_transaction()))
            return await original_stream(db, *args, **kwargs)

        async def observe_lock(db, context):
            observed.append(("lock", db.sync_session.get_transaction()))
            await original_lock(db, context)

        monkeypatch.setattr(AsyncSession, "stream", observe_stream)
        monkeypatch.setattr(invoice_delivery, "_lock_tenant", observe_lock)
        blocked = await session.call_tool(
            "invoices.email", {"invoiceId": str(document_id), "idempotencyKey": str(uuid.uuid4())}
        )
        assert blocked.isError and "previously delivered" in blocked.content[0].text
        assert [stage for stage, _ in observed] == ["scan", "lock"]
        assert observed[0][1] is not observed[1][1] and not observed[0][1].is_active
        async with SessionFactory() as db, db.begin():
            doc = await db.get(SalesDocument, document_id)
            (await db.get(Party, doc.party_id)).email = old_recipient
        replay = await session.call_tool(
            "invoices.email", {"invoiceId": str(document_id), "idempotencyKey": str(uuid.uuid4())}
        )
        assert not replay.isError and replay.structuredContent["messageId"] == "old-google-id"
        assert not sent

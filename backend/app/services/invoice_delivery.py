"""Fiscal invoice delivery. Gmail never runs before the durable claim commits."""

import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.core.ios_catalog_access import check_billing_membership
from app.core.ios_permissions import IOS_CLIENT_ID
from app.integrations.sri.soap import production_endpoints
from app.models.billing import InvoiceEmailDispatch, SalesDocument
from app.models.masters import Party
from app.models.platform import (
    AutomationSettings,
    IdempotencyRecord,
    OutboxEvent,
    Tenant,
    TenantFiscalSettings,
)
from app.schemas.billing import InvoiceDeliveryStatus, InvoiceEmailPreviewRead, InvoiceEmailRead
from app.services import billing, crm_integrations
from app.services.unit_of_work import append_audit, canonical_hash

FiscalEnvironment = Literal["PRODUCTION", "TEST", "UNCONFIGURED"]


def require_request_key(value: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise HTTPException(422, "A UUID Idempotency-Key is required") from None
    if str(parsed) != value.lower():
        raise HTTPException(422, "A UUID Idempotency-Key is required")


def require_scope(context: AuthContext, scope: str) -> None:
    if context.actor_type != "USER" or scope not in context.scopes:
        raise HTTPException(403, "Invoice delivery permission required")


async def fiscal_environment(session: AsyncSession, doc: SalesDocument) -> FiscalEnvironment:
    settings = get_settings()
    fiscal = await session.get(TenantFiscalSettings, doc.tenant_id)
    if not fiscal:
        return "UNCONFIGURED"
    if doc.access_key is not None:
        key = doc.access_key
        if len(key) != 49 or not key.isascii() or not key.isdigit() or key[23] not in "12":
            return "UNCONFIGURED"
        if key[23] == "1":
            return "TEST"
    if fiscal.sri_environment == "1" or settings.SRI_TRANSMISSION_MODE != "soap":
        return "TEST"
    if (
        production_endpoints(settings.SRI_RECEPTION_URL, settings.SRI_AUTHORIZATION_URL)
        and settings.SRI_ENVIRONMENT == "2"
        and fiscal.sri_environment == "2"
        and settings.APP_ENV in {"production", "release"}
    ):
        return "PRODUCTION"
    return "UNCONFIGURED"


async def require_production(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID, *, issue: bool = False
) -> SalesDocument:
    doc = await billing.get_sales_document(session, context, document_id)
    if doc.document_type != "INVOICE":
        raise HTTPException(404, "Invoice not found")
    if await fiscal_environment(session, doc) != "PRODUCTION":
        raise HTTPException(409, "invoice_environment_not_production")
    if issue and doc.access_key:
        raise HTTPException(409, "invoice_already_issued")
    if not issue and (
        doc.status != "AUTHORIZED"
        or not doc.access_key
        or doc.authorization_number != doc.access_key
    ):
        raise HTTPException(422, "Only authorized invoices can be emailed")
    return doc


async def _prepare(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID
) -> tuple[billing.InvoiceEmailDelivery, InvoiceEmailPreviewRead]:
    await require_production(session, context, document_id)
    delivery = await billing.prepare_invoice_email(session, context, document_id)
    mailbox = await crm_integrations.prepare_google_sender(session, context)
    if not delivery.sender_address:
        if not mailbox:
            raise HTTPException(422, "Google Workspace sender is missing")
        delivery = replace(delivery, sender_address=mailbox)
    if delivery.report_object_key and not delivery.report_sha256:
        raise HTTPException(422, "Approved report checksum is missing")
    preview = billing.email_preview(delivery)
    preview.preview_digest = canonical_hash(
        {
            "tenant": context.tenant_id,
            "invoice": document_id,
            "mailbox": mailbox,
            "preview": preview.model_dump(mode="json", exclude={"preview_digest"}),
            "artifacts": [
                (k, a.id, a.version, a.object_key, a.sha256)
                for k, a in sorted(delivery.artifacts.items())
            ],
            "report": [delivery.report_object_key, delivery.report_sha256],
        }
    )
    return delivery, preview


async def preview_email(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID
) -> InvoiceEmailPreviewRead:
    require_scope(context, "invoices:email")
    _, preview = await _prepare(session, context, document_id)
    return preview


async def _lock_tenant(session: AsyncSession, context: AuthContext) -> None:
    await session.scalar(select(Tenant.id).where(Tenant.id == context.tenant_id).with_for_update())


async def _web_receipt(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID, recipient: str | None
) -> InvoiceEmailRead | None:
    if not recipient:
        return None
    payload = await session.scalar(
        select(IdempotencyRecord.response_body)
        .where(
            IdempotencyRecord.tenant_id == context.tenant_id,
            IdempotencyRecord.operation == "invoices.email",
            IdempotencyRecord.status == "COMPLETED",
            IdempotencyRecord.request_hash
            == canonical_hash({"invoice_id": str(document_id), "recipient": recipient}),
        )
        .order_by(IdempotencyRecord.created_at.desc())
        .limit(1)
    )
    return InvoiceEmailRead.model_validate(payload) if payload else None


async def _historical_mcp_receipt(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID
) -> dict[str, object] | None:
    completed = await session.scalar(
        select(InvoiceEmailDispatch.provider_message_id).where(
            InvoiceEmailDispatch.tenant_id == context.tenant_id,
            InvoiceEmailDispatch.document_id == document_id,
            InvoiceEmailDispatch.provider_message_id.is_not(None),
        ).limit(1)
    )
    if completed is not None:
        # Completed claims are permanent and will be checked again under the tenant lock.
        return None

    # The old receipt binds the invoice to its actual recipient only through a hash.
    # Since the dispatch migration this operation no longer creates idempotency rows.
    created_at = select(SalesDocument.created_at).where(
        SalesDocument.tenant_id == context.tenant_id,
        SalesDocument.id == document_id,
    ).scalar_subquery()
    receipts = await session.stream(
        select(IdempotencyRecord.request_hash, IdempotencyRecord.response_body)
        .where(
            IdempotencyRecord.tenant_id == context.tenant_id,
            IdempotencyRecord.operation == "invoices.email",
            IdempotencyRecord.status == "COMPLETED",
            IdempotencyRecord.created_at >= created_at,
        )
        .order_by(IdempotencyRecord.created_at.desc())
        .execution_options(yield_per=128)
    )
    try:
        async for request_hash, body in receipts:
            if not isinstance(body, dict):
                continue
            recipient = body.get("recipient")
            if recipient and request_hash == canonical_hash(
                {"invoice_id": str(document_id), "recipient": recipient}
            ):
                return body
        return None
    finally:
        await receipts.close()


async def _audit(
    session: AsyncSession, context: AuthContext, row: InvoiceEmailDispatch, action: str
) -> None:
    await append_audit(
        session,
        context=context,
        action=action,
        entity_type="sales_document",
        entity_id=str(row.document_id),
        correlation_id=row.provider_reference.split("@")[0],
        idempotency_key=row.idempotency_key,
        details={"preview_digest": row.preview_digest},
    )


def _receipt(row: InvoiceEmailDispatch) -> InvoiceEmailRead | None:
    if row.provider_message_id:
        return InvoiceEmailRead.model_validate(
            {**row.envelope, "messageId": row.provider_message_id}
        )
    return None


async def _finish(
    session: AsyncSession,
    context: AuthContext,
    reference: str,
    message_id: str,
    *,
    reconciled: bool = False,
) -> InvoiceEmailRead:
    # Token refresh may have written the Gmail account. Release it before acquiring the
    # tenant lock, in the same order as the initial reservation.
    if session.in_transaction():
        await session.commit()
    await _lock_tenant(session, context)
    row = await session.get(
        InvoiceEmailDispatch, (context.tenant_id, reference), populate_existing=True
    )
    assert row is not None
    if row.provider_message_id is None:
        row.provider_message_id = message_id
        await _audit(
            session, context, row, "invoice.email_reconciled" if reconciled else "invoice.emailed"
        )
        session.add(
            OutboxEvent(
                tenant_id=context.tenant_id,
                event_type="invoice.emailed",
                aggregate_type="sales_document",
                aggregate_id=str(row.document_id),
                correlation_id=reference.split("@")[0],
                available_at=datetime.now(UTC),
                payload={"entity_id": str(row.document_id), "action": "invoice.emailed"},
            )
        )
    result = _receipt(row)
    assert result is not None
    await session.commit()
    return result


async def _reconcile_pending(
    session: AsyncSession, context: AuthContext, reference: str
) -> InvoiceEmailRead | None:
    try:
        message_id = await crm_integrations.find_sent_reference(session, context, reference)
    except (httpx.HTTPError, HTTPException, ValueError):
        return None
    if not message_id:
        return None
    return await _finish(session, context, reference, message_id, reconciled=True)


async def delivery_status(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
    *,
    recipient_hash: str | None = None,
) -> InvoiceDeliveryStatus:
    doc = await billing.get_sales_document(session, context, document_id)
    if doc.document_type != "INVOICE":
        raise HTTPException(404, "Invoice not found")
    environment = await fiscal_environment(session, doc)
    recipient = await session.scalar(
        select(Party.email).where(Party.tenant_id == context.tenant_id, Party.id == doc.party_id)
    )
    deliveries = select(InvoiceEmailDispatch).where(
        InvoiceEmailDispatch.tenant_id == context.tenant_id,
        InvoiceEmailDispatch.document_id == document_id,
    )
    catalog_hash = hashlib.sha256(recipient.encode()).hexdigest() if recipient else None
    lookup_hash = catalog_hash if context.client_id == IOS_CLIENT_ID else recipient_hash
    if lookup_hash is not None or context.client_id == IOS_CLIENT_ID:
        deliveries = deliveries.where(
            (InvoiceEmailDispatch.recipient_hash == lookup_hash)
            | InvoiceEmailDispatch.provider_message_id.is_(None)
        )
    row = await session.scalar(deliveries.order_by(InvoiceEmailDispatch.created_at.desc()).limit(1))
    if row is None:
        receipt = (
            await _web_receipt(session, context, document_id, recipient)
            if lookup_hash in (None, catalog_hash)
            else None
        )
    else:
        receipt = _receipt(row)
        can_reconcile = (
            "invoices:email" if context.client_id == IOS_CLIENT_ID else "invoices:write"
        ) in context.scopes
        if not receipt and context.actor_id == row.actor_id and can_reconcile:
            receipt = await _reconcile_pending(session, context, row.provider_reference)
            if receipt:
                if (
                    context.client_id == IOS_CLIENT_ID or lookup_hash is not None
                ) and row.recipient_hash != lookup_hash:
                    return await delivery_status(
                        session, context, document_id, recipient_hash=recipient_hash
                    )
    return InvoiceDeliveryStatus(
        fiscal_environment=environment,
        email_status="SENT" if receipt else "PENDING" if row else "NOT_SENT",
        receipt=receipt,
    )


async def send_registered_invoice(
    session: AsyncSession, context: AuthContext, document_id: uuid.UUID, *, key: str
) -> InvoiceEmailRead:
    try:
        return await send_email(
            session, context, document_id, recipient=None, digest=None, key=key, mcp_delivery=True,
        )
    except HTTPException as exc:
        if exc.detail != "invoice_email_pending":
            raise
        # Recover only this caller's MCP request. Gmail lookup never sends a message.
        claim = await session.scalar(
            select(InvoiceEmailDispatch).where(
                InvoiceEmailDispatch.tenant_id == context.tenant_id,
                InvoiceEmailDispatch.actor_id == context.actor_id,
                InvoiceEmailDispatch.document_id == document_id,
                InvoiceEmailDispatch.idempotency_key == key,
                InvoiceEmailDispatch.request_hash == _mcp_email_hash(document_id),
            )
        )
        if claim:
            receipt = _receipt(claim) or await _reconcile_pending(
                session, context, claim.provider_reference
            )
            if receipt:
                return receipt
        raise


def _mcp_email_hash(document_id: uuid.UUID) -> str:
    return canonical_hash({"invoice_id": str(document_id), "channel": "mcp"})


async def send_email(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
    *,
    recipient: str | None,
    digest: str | None,
    key: str,
    resend: bool = False,
    mcp_delivery: bool = False,
) -> InvoiceEmailRead:
    native = context.client_id == IOS_CLIENT_ID
    restricted_delivery = native or mcp_delivery
    if restricted_delivery:
        require_scope(context, "invoices:email")
    if native:
        require_request_key(key)
        if not digest:
            raise HTTPException(409, "invoice_email_preview_changed")
        if resend:
            raise HTTPException(422, "Explicit resend is not available on iOS")
    payload = {"invoice_id": str(document_id), "recipient": recipient}
    request_hash = canonical_hash({**payload, "resend": resend, "digest": digest, "native": native})
    if mcp_delivery:
        if recipient is not None or digest is not None or resend:
            raise HTTPException(422, "MCP delivers only to the registered customer")
        request_hash = _mcp_email_hash(document_id)
    if session.in_transaction():
        await session.rollback()
    historical_receipt = None
    if mcp_delivery:
        # Legacy rows are immutable. Release this read transaction before serializing
        # current dispatches, membership checks and the decision to send.
        async with session.begin():
            historical_receipt = await _historical_mcp_receipt(session, context, document_id)
    async with session.begin():
        await _lock_tenant(session, context)
        if mcp_delivery:
            enabled = await session.scalar(
                select(AutomationSettings.writes_enabled)
                .where(AutomationSettings.tenant_id == context.tenant_id)
                .with_for_update()
            )
            if not enabled:
                raise HTTPException(403, "Automation writes are disabled for this tenant")
        if restricted_delivery:
            await check_billing_membership(session, context)
        await billing.get_sales_document(session, context, document_id)
        replay = await session.scalar(
            select(InvoiceEmailDispatch).where(
                InvoiceEmailDispatch.tenant_id == context.tenant_id,
                InvoiceEmailDispatch.actor_id == context.actor_id,
                InvoiceEmailDispatch.idempotency_key == key,
            )
        )
        if replay:
            if replay.request_hash != request_hash:
                raise HTTPException(409, "invoice_email_key_conflict")
            prior = _receipt(replay)
            if prior:
                return prior
            raise HTTPException(409, "invoice_email_pending")
        # Preserve promises of an idempotency key issued before the durable dispatch migration.
        legacy = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == context.tenant_id,
                IdempotencyRecord.actor_id == context.actor_id,
                IdempotencyRecord.operation == "invoices.email",
                IdempotencyRecord.idempotency_key == key,
            )
        )
        if legacy:
            if mcp_delivery or resend or legacy.request_hash != canonical_hash(payload):
                raise HTTPException(409, "invoice_email_key_conflict")
            if legacy.status == "COMPLETED" and legacy.response_body:
                return InvoiceEmailRead.model_validate(legacy.response_body)
            raise HTTPException(409, "invoice_email_pending")
        invoice_claims = select(InvoiceEmailDispatch).where(
            InvoiceEmailDispatch.tenant_id == context.tenant_id,
            InvoiceEmailDispatch.document_id == document_id,
        )
        pending = await session.scalar(
            invoice_claims.where(InvoiceEmailDispatch.provider_message_id.is_(None)).limit(1)
        )
        if pending:
            raise HTTPException(409, "invoice_email_pending")
        if restricted_delivery:
            delivery, preview = await _prepare(session, context, document_id)
            if mcp_delivery:
                if delivery.report_object_key:
                    raise HTTPException(
                        422, "Invoice includes a report requiring separate delivery"
                    )
                recipient = preview.recipient
                digest = preview.preview_digest
            elif preview.preview_digest != digest or preview.recipient != recipient:
                raise HTTPException(409, "invoice_email_preview_changed")
        else:
            delivery = await billing.prepare_invoice_email(session, context, document_id)
            preview = billing.email_preview(delivery)
        if not recipient:
            raise HTTPException(422, "Invoice customer has no registered email")
        recipient_hash = hashlib.sha256(recipient.encode()).hexdigest()
        if not resend:
            matching_claims = (
                invoice_claims if mcp_delivery
                else invoice_claims.where(InvoiceEmailDispatch.recipient_hash == recipient_hash)
            )
            delivered = await session.scalar(
                matching_claims.order_by(InvoiceEmailDispatch.created_at.desc()).limit(1)
            )
            if mcp_delivery and delivered and delivered.recipient_hash != recipient_hash:
                raise HTTPException(409, "Invoice already delivered to a different address")
            if delivered:
                existing_receipt = _receipt(delivered)
            elif mcp_delivery:
                if historical_receipt and historical_receipt.get("recipient") != recipient:
                    raise HTTPException(
                        409, "Invoice previously delivered; review delivery history"
                    )
                existing_receipt = (
                    InvoiceEmailRead.model_validate(historical_receipt)
                    if historical_receipt else None
                )
            else:
                existing_receipt = await _web_receipt(session, context, document_id, recipient)
            if existing_receipt:
                return existing_receipt
        attachments = await billing.load_invoice_attachments(delivery, verify=restricted_delivery)
        reference = f"{uuid.uuid4()}@iaerp.invalid"
        claim = InvoiceEmailDispatch(
            tenant_id=context.tenant_id,
            document_id=document_id,
            actor_id=context.actor_id,
            idempotency_key=key,
            preview_digest=digest or canonical_hash(preview.model_dump(mode="json")),
            recipient_hash=recipient_hash,
            request_hash=request_hash,
            provider_reference=reference,
            envelope={
                "recipient": recipient,
                "senderAddress": preview.sender_address,
                "senderName": preview.sender_name,
                "attachmentNames": preview.attachment_names,
            },
        )
        session.add(claim)
        await _audit(session, context, claim, "invoice.email_requested")
    # The claim survives timeouts, process death and a lost database commit after Gmail accepted.
    # Only the owner of this new claim can reach the single provider call.
    try:
        sent = await billing.send_prepared_invoice(
            session, context, delivery, recipient, attachments, provider_reference=reference
        )
    except crm_integrations.GoogleSendRejected as exc:
        await session.rollback()
        async with session.begin():
            await _lock_tenant(session, context)
            rejected = await session.get(InvoiceEmailDispatch, (context.tenant_id, reference))
            if (
                rejected
                and rejected.provider_reference == reference
                and not rejected.provider_message_id
            ):
                await _audit(session, context, rejected, "invoice.email_rejected")
                await session.delete(rejected)
        if exc.status_code in {422, 503}:
            raise HTTPException(exc.status_code, exc.detail) from None
        raise HTTPException(422, "invoice_email_rejected") from None
    except (httpx.HTTPError, HTTPException, ValueError, KeyError):
        await session.rollback()
        raise HTTPException(409, "invoice_email_pending") from None
    return await _finish(session, context, reference, sent.message_id)

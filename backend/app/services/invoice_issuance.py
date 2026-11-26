"""Issue a sales document through the common REST and MCP unit of work."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.grok_permissions import GROK_CLIENT_ID
from app.core.ios_catalog_access import check_billing_membership
from app.core.ios_permissions import IOS_CLIENT_ID
from app.models.billing import SalesDocument, SRITransmission
from app.models.legal_commercial import BillingProposal
from app.models.masters import Party
from app.models.platform import AutomationSettings, OperationRecord
from app.schemas.platform import OperationRead
from app.services import billing, crm_integrations, invoice_delivery
from app.services.unit_of_work import execute_idempotent


async def _check_email_delivery(
    session: AsyncSession, context: AuthContext, document: SalesDocument
) -> None:
    invoice_delivery.require_scope(context, "invoices:email")
    recipient = await session.scalar(
        select(Party.email).where(
            Party.tenant_id == context.tenant_id,
            Party.id == document.party_id,
            Party.active.is_(True),
        )
    )
    address = TypeAdapter(EmailStr)
    try:
        address.validate_python(recipient)
    except ValidationError as exc:
        raise HTTPException(422, "Invoice customer has no valid registered email") from exc
    sender = await crm_integrations.configured_google_sender(session, context)
    try:
        address.validate_python(sender)
    except ValidationError as exc:
        raise HTTPException(422, "Google Workspace sender address is invalid") from exc
    report = await session.scalar(
        select(BillingProposal.id).where(
            BillingProposal.tenant_id == context.tenant_id,
            BillingProposal.sales_document_id == document.id,
            BillingProposal.report_required | BillingProposal.report_approved_at.is_not(None),
        )
    )
    if report is not None:
        raise HTTPException(422, "Invoice includes a report requiring separate delivery")


async def issue_invoice(
    session: AsyncSession, context: AuthContext, invoice_id: uuid.UUID, idempotency_key: str
) -> dict[str, object]:
    protected = context.client_id in {IOS_CLIENT_ID, GROK_CLIENT_ID}

    async def issue() -> tuple[str, dict[str, object]]:
        if protected:
            invoice_delivery.require_scope(context, "invoices:issue")
            if context.client_id == IOS_CLIENT_ID:
                invoice_delivery.require_request_key(idempotency_key)
            else:
                # Recheck under the unit-of-work tenant lock, after MCP admission.
                automation = await session.get(AutomationSettings, context.tenant_id)
                if automation is None or not automation.writes_enabled:
                    raise HTTPException(403, "Automation writes are disabled for this tenant")
            await check_billing_membership(session, context)
            draft = await invoice_delivery.require_production(
                session, context, invoice_id, issue=True
            )
            if context.client_id == GROK_CLIENT_ID:
                await _check_email_delivery(session, context, draft)
        correlation_id = str(uuid.uuid4())
        document = await billing.issue_document(
            session,
            context,
            invoice_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        if protected:
            session.add(
                SRITransmission(
                    tenant_id=context.tenant_id,
                    sales_document_id=document.id,
                    access_key=document.access_key,
                    status="PENDING",
                    attempts=0,
                    messages=[],
                )
            )
        operation = OperationRecord(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            operation_type="invoices.issue",
            status="PROCESSING",
            correlation_id=correlation_id,
            result={"sales_document_id": str(document.id), "status": document.status},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        session.add(operation)
        await session.flush()
        response = OperationRead(
            operation_id=operation.id,
            status=operation.status,
            correlation_id=operation.correlation_id,
            created_at=operation.created_at,
            expires_at=operation.expires_at,
            result=operation.result,
            error=operation.error,
        ).model_dump(mode="json", by_alias=True)
        return str(document.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="invoices.issue",
        idempotency_key=idempotency_key,
        request_payload={"invoice_id": str(invoice_id)},
        action="invoice.issued",
        entity_type="sales_document",
        callback=issue,
        event_type="invoice.signed",
        # Workers in previous releases also recognize this durable-reception flag.
        event_payload={"native_confirmed": True} if protected else None,
    )

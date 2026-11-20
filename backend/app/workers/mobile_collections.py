"""Send a confirmed reminder once. Reconcile ambiguous results by Message-ID."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.core.ios_collection_access import check_collection_membership
from app.core.ios_permissions import IOS_CLIENT_ID
from app.db.session import SessionFactory
from app.models.receivables import CollectionReminder
from app.schemas.ios_collections import ReminderConfirmation
from app.services import crm_integrations, mobile_collections, receivables


async def deliver(tenant: uuid.UUID, reminder_id: uuid.UUID) -> bool:
    query = select(CollectionReminder).where(
        CollectionReminder.tenant_id == tenant,
        CollectionReminder.id == reminder_id,
        CollectionReminder.native_confirmation.is_not(None),
    )
    reference = f"collection-{reminder_id}@iaerp.invalid"
    async with SessionFactory() as session, session.begin():
        record = await session.scalar(query.with_for_update())
        if record is None or record.status not in {"PENDING", "PROCESSING"}:
            return False
        assert record.native_confirmation is not None and record.receivable_id is not None
        actor = record.native_confirmation["actor"]
        context = AuthContext(
            tenant_id=tenant,
            actor_id=actor,
            actor_type="USER",
            roles=frozenset(),
            scopes=frozenset({"collections:notify"}),
            token_id=str(reminder_id),
            client_id=IOS_CLIENT_ID,
        )
        account_id = record.receivable_id
        confirmation = ReminderConfirmation.model_validate(
            {k: v for k, v in record.native_confirmation.items() if k != "actor"}
        )
        reconcile = record.delivery_status == "UNCERTAIN"
        if not reconcile:
            # Commit before the network call. Neither a worker crash nor a database
            # write failure after Gmail accepts can turn the reservation into a new send.
            record.status = "PROCESSING"
            record.delivery_status = "UNCERTAIN"
            record.attempts += 1
    async with SessionFactory() as session, session.begin():
        if reconcile:
            record = await session.scalar(query.with_for_update())
            if record is None or record.delivery_status != "UNCERTAIN":
                return False
            receipt = await crm_integrations.find_sent_reference(session, context, reference)
            if not receipt:
                # Celery retries this lookup; the reserved message is never retransmitted.
                raise RuntimeError("El proveedor aún no confirma el correo de cobranza.")
        else:
            try:
                # Same lock order as an interactive mutation, including pending
                # terms, payments and permissions that changed after confirmation.
                await check_collection_membership(session, context)
                account = await receivables.lock_receivable(
                    session, tenant_id=tenant, receivable_id=account_id
                )
                view = await mobile_collections.detail(
                    session, tenant, account_id, exclude_reminder_id=reminder_id
                )
                mobile_collections.require_current_confirmation(view, confirmation)
                subject, plain, html = await receivables._render_receivable_email(
                    session,
                    tenant_id=tenant,
                    receivable=account,
                    party_name=view.customer_name,
                    body_override=None,
                )
            except HTTPException as exc:
                record = await session.scalar(query.with_for_update())
                if record is not None:
                    record.status = "SKIPPED"
                    record.delivery_status = "UNKNOWN"
                    record.error_message = str(exc.detail)[:500]
                return False

            record = await session.scalar(query.with_for_update())
            if (
                record is None
                or record.status != "PROCESSING"
                or record.delivery_status != "UNCERTAIN"
            ):
                return False
            try:
                receipt = await crm_integrations.send_google_email(
                    session,
                    context,
                    recipient=confirmation.expected_recipient,
                    subject=subject,
                    message=plain,
                    html_message=html,
                    provider_reference=reference,
                )
            except crm_integrations.GoogleSendRejected:
                record.status = "FAILED"
                record.delivery_status = "FAILED"
                record.error_message = (
                    "El proveedor rechazó el correo. Revisa la conexión de correo."
                )
                return False
            # Other errors may occur after the provider accepted. Roll back this
            # transaction, leaving the durable reservation for read-only reconciliation.
        record.status = "SENT"
        record.delivery_status = "SENT"
        record.sent_at = datetime.now(UTC)
        record.provider_message_id = receipt
        record.error_message = None
        return True

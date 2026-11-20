import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext, require_scopes
from app.core.ios_catalog_access import CatalogKey, CatalogSession
from app.core.ios_collection_access import check_collection_membership
from app.core.timezones import today_in_fiscal_timezone
from app.models.billing import SalesDocument
from app.models.receivables import CollectionReminder, Receivable
from app.schemas.ios_collections import (
    CollectionAccount,
    CollectionWrite,
    PromiseChange,
    ReminderConfirmation,
    TermChange,
)
from app.services import mobile_collections as collections
from app.services import receivables
from app.services.unit_of_work import execute_idempotent

router = APIRouter(prefix="/collections/accounts")
Read = Annotated[AuthContext, Depends(require_scopes("receivables:read"))]
Terms = Annotated[AuthContext, Depends(require_scopes("receivables:read", "collections:terms"))]
Notify = Annotated[AuthContext, Depends(require_scopes("receivables:read", "collections:notify"))]


@router.get("", response_model=list[CollectionAccount])
async def list_accounts(session: CatalogSession, context: Read) -> list[CollectionAccount]:
    return await collections.accounts(session, context.tenant_id)


@router.get("/{account_id}", response_model=CollectionAccount)
async def get_account(
    account_id: uuid.UUID, session: CatalogSession, context: Read
) -> CollectionAccount:
    return await collections.detail(session, context.tenant_id, account_id)


async def change(
    session: CatalogSession,
    context: AuthContext,
    account_id: uuid.UUID,
    key: str,
    action: str,
    data: CollectionWrite,
    mutate: Callable[[Receivable, CollectionAccount], Awaitable[uuid.UUID | None]],
) -> dict[str, Any]:
    async def apply() -> tuple[str, dict[str, Any]]:
        await check_collection_membership(session, context)
        account = await receivables.lock_receivable(
            session, tenant_id=context.tenant_id, receivable_id=account_id
        )
        view = await collections.detail(session, context.tenant_id, account_id)
        if (
            await session.scalar(
                select(SalesDocument.status).where(
                    SalesDocument.tenant_id == context.tenant_id,
                    SalesDocument.id == account.sales_document_id,
                )
            )
            != "AUTHORIZED"
        ):
            raise HTTPException(409, "La factura requiere autorización para gestionar la cobranza.")
        previous_promise = account.promised_date
        receipt = await mutate(account, view)
        if action == "promise":
            audit.update(
                previous_date=previous_promise.isoformat() if previous_promise else None,
                promised_date=account.promised_date.isoformat() if account.promised_date else None,
            )
        await session.flush()
        current = await collections.detail(session, context.tenant_id, account_id)
        result = current.model_dump(mode="json", by_alias=True)
        if receipt:
            result["_receiptId"] = str(receipt)
        return str(account_id), result

    audit: dict[str, Any] = {}
    result = await execute_idempotent(
        session,
        context=context,
        operation=f"collections.{action}",
        idempotency_key=key,
        request_payload={"account": str(account_id), **data.model_dump(mode="json")},
        action=f"collection.{action}",
        entity_type="receivable",
        callback=apply,
        audit_details=audit,
    )
    if "_receiptId" in result:
        result = dict(result)
        reminder = await session.scalar(
            select(CollectionReminder).where(
                CollectionReminder.id == uuid.UUID(result.pop("_receiptId")),
                CollectionReminder.tenant_id == context.tenant_id,
                CollectionReminder.receivable_id == account_id,
            )
        )
        if reminder:
            result.update(
                lastReminderStatus=collections.shown_status(reminder),
                lastReminderAt=(reminder.sent_at or reminder.created_at).isoformat(),
            )
    return result


@router.put("/{account_id}/promise", response_model=CollectionAccount)
async def set_promise(
    account_id: uuid.UUID,
    data: PromiseChange,
    session: CatalogSession,
    context: Terms,
    idempotency_key: CatalogKey,
) -> dict[str, Any]:
    async def apply(account: Receivable, view: CollectionAccount) -> None:
        if data.previous_promised_date != view.promised_date:
            raise HTTPException(409, "La promesa cambió. Actualiza la cuenta para revisarla.")
        if data.promised_date and data.promised_date < today_in_fiscal_timezone():
            raise HTTPException(422, "Elige hoy o una fecha futura para la promesa.")
        account.promised_date = data.promised_date

    return await change(session, context, account_id, idempotency_key, "promise", data, apply)


@router.put("/{account_id}/due-date", response_model=CollectionAccount)
async def change_due_date(
    account_id: uuid.UUID,
    data: TermChange,
    session: CatalogSession,
    context: Terms,
    idempotency_key: CatalogKey,
) -> dict[str, Any]:
    async def apply(account: Receivable, view: CollectionAccount) -> None:
        if data.installment_id is None and view.installment_count != 1:
            raise HTTPException(422, "Selecciona la cuota que quieres ajustar.")
        selected = (
            next((i for i in view.installments if i.id == data.installment_id), None)
            if data.installment_id
            else view.installments[0]
        )
        if selected is None or selected.open_amount <= 0:
            raise HTTPException(409, "Selecciona una cuota pendiente de esta cuenta.")
        if selected.due_date != data.previous_due_date:
            raise HTTPException(409, "El vencimiento cambió. Actualiza la cuenta para revisarlo.")
        await receivables.correct_receivable_due_date(
            session,
            context,
            receivable_id=account.id,
            installment_id=selected.id,
            due_date=data.due_date,
            reason=data.reason,
            correlation_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
        )

    return await change(session, context, account_id, idempotency_key, "due_date", data, apply)


@router.put("/{account_id}/enable-reminders", response_model=CollectionAccount)
async def enable_reminders(
    account_id: uuid.UUID,
    data: CollectionWrite,
    session: CatalogSession,
    context: Notify,
    idempotency_key: CatalogKey,
) -> dict[str, Any]:
    async def apply(account: Receivable, view: CollectionAccount) -> None:
        if not view.can_enable_reminders and not view.collection_enabled:
            raise HTTPException(
                409, view.reminder_blocked_reason or "No se pueden habilitar los recordatorios."
            )
        await receivables.update_receivable_collection_policy(
            session, context, receivable_id=account.id, enabled=True
        )

    return await change(
        session, context, account_id, idempotency_key, "enable_reminders", data, apply
    )


@router.post("/{account_id}/reminder", response_model=CollectionAccount)
async def send_individual_reminder(
    account_id: uuid.UUID,
    data: ReminderConfirmation,
    session: CatalogSession,
    context: Notify,
    idempotency_key: CatalogKey,
) -> dict[str, Any]:
    async def apply(account: Receivable, view: CollectionAccount) -> uuid.UUID:
        return await collections.queue_email(session, context, view, data)

    return await change(session, context, account_id, idempotency_key, "reminder", data, apply)

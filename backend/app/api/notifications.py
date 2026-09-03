"""Canal de avisos internos: estado, remitente, prueba y webhook (F2).

Deliberadamente pequeno. La configuracion completa de reglas, plantillas y la
bitacora es F4; aqui solo esta lo que F2 necesita para que alguien pueda
**verificar que el correo sale** antes de encender ninguna regla.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.integrations.notifications.email_sender import EmailMessage
from app.models.legal_commercial import PartyBillingSchedule
from app.models.masters import Party
from app.models.notifications import (
    NotificationChannelAccount,
    NotificationDelivery,
    NotificationEvent,
)
from app.models.platform import Tenant
from app.schemas.notifications import (
    ChannelAccountRead,
    ChannelAccountUpdate,
    ChannelTestRequest,
    ChannelTestResult,
    NotificationBillingScheduleCreate,
    NotificationBillingScheduleRead,
    NotificationBillingScheduleUpdate,
    NotificationDeliveryRead,
    NotificationEventDetailRead,
    NotificationEventRead,
    NotificationRuleRead,
    NotificationRuleUpdate,
    NotificationTemplatePreviewRequest,
    NotificationTemplatePreviewResult,
    NotificationTemplateRead,
    NotificationTemplateUpdate,
)
from app.services import legal_commercial
from app.services.notifications import admin, channels, webhooks
from app.services.unit_of_work import execute_idempotent

router = APIRouter(tags=["notifications"])

Session = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=16, max_length=128),
]


async def _company_name(session: AsyncSession, context: AuthContext) -> str:
    tenant = await session.get(Tenant, context.tenant_id)
    return tenant.name if tenant is not None else ""


@router.get(
    "/notifications/channel-account",
    response_model=ChannelAccountRead,
    summary="Estado del canal de correo de los avisos internos",
)
async def get_channel_account(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
) -> ChannelAccountRead:
    status = await channels.channel_status(
        session,
        tenant_id=context.tenant_id,
        company_name=await _company_name(session, context),
    )
    return ChannelAccountRead(
        provider=status.provider,
        platform_key_configured=status.platform_key_configured,
        sender_email=status.sender_email,
        sender_name=status.sender_name,
        reply_to=status.reply_to,
        ready=status.ready,
        blocking_reason=status.blocking_reason,
    )


@router.put(
    "/notifications/channel-account",
    response_model=ChannelAccountRead,
    summary="Configurar el remitente de los avisos internos",
)
async def put_channel_account(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
    data: ChannelAccountUpdate,
) -> ChannelAccountRead:
    account = await session.get(NotificationChannelAccount, context.tenant_id)
    if account is None:
        account = NotificationChannelAccount(tenant_id=context.tenant_id)
        session.add(account)
    account.sender_name = data.sender_name
    account.sender_email = str(data.sender_email) if data.sender_email else None
    account.reply_to = str(data.reply_to) if data.reply_to else None
    account.provider = "BREVO" if channels.platform_sender_configured() else "STUB"
    await session.flush()
    status = await channels.channel_status(
        session,
        tenant_id=context.tenant_id,
        company_name=await _company_name(session, context),
    )
    await session.commit()
    return ChannelAccountRead(
        provider=status.provider,
        platform_key_configured=status.platform_key_configured,
        sender_email=status.sender_email,
        sender_name=status.sender_name,
        reply_to=status.reply_to,
        ready=status.ready,
        blocking_reason=status.blocking_reason,
    )


@router.post(
    "/notifications/channel-account/test",
    response_model=ChannelTestResult,
    summary="Enviar un correo de prueba",
)
async def post_channel_test(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
    data: ChannelTestRequest,
) -> ChannelTestResult:
    """Prueba la cadena completa sin encender ninguna regla.

    Existe porque la alternativa es descubrir que el dominio no estaba
    autenticado cuando ya salio un aviso real al equipo del cliente.
    """
    company_name = await _company_name(session, context)
    status = await channels.channel_status(
        session, tenant_id=context.tenant_id, company_name=company_name
    )
    if not status.ready and status.blocking_reason is not None:
        raise HTTPException(status_code=422, detail=status.blocking_reason)

    identity = await channels.resolve_sender_identity(
        session, tenant_id=context.tenant_id, company_name=company_name
    )
    sender = channels.build_email_sender()
    result = await sender.send(
        EmailMessage(
            recipient=str(data.recipient),
            subject=f"Prueba de avisos de IAERP - {company_name}",
            body_text=(
                "Este es un correo de prueba del modulo de avisos de IAERP.\n\n"
                "Si lo recibiste, el canal funciona y ya se pueden encender "
                "reglas. Ningun aviso sale hasta que alguien las active."
            ),
            body_html=(
                "<p>Este es un correo de prueba del modulo de avisos de IAERP.</p>"
                "<p>Si lo recibiste, el canal funciona y ya se pueden encender "
                "reglas. Ningun aviso sale hasta que alguien las active.</p>"
            ),
            sender_email=identity.email,
            sender_name=identity.name,
            reply_to=identity.reply_to,
        )
    )
    return ChannelTestResult(
        provider=result.provider,
        status=result.status,
        provider_message_id=result.provider_message_id,
        error_message=result.error_message,
    )


def _period_label(payload: dict[str, object]) -> str | None:
    value = payload.get("period_label")
    return value if isinstance(value, str) else None


def _event_read(event: NotificationEvent) -> NotificationEventRead:
    return NotificationEventRead(
        id=event.id,
        rule_id=event.rule_id,
        rule_type=event.rule_type,
        status=event.status,
        scheduled_at=event.scheduled_at,
        attempts=event.attempts,
        error_message=event.error_message,
        sent_at=event.sent_at,
        ack_at=event.ack_at,
        ack_by=event.ack_by,
        period_label=_period_label(event.payload),
    )


def _event_detail_read(
    event: NotificationEvent, deliveries: list[NotificationDelivery]
) -> NotificationEventDetailRead:
    return NotificationEventDetailRead(
        id=event.id,
        rule_id=event.rule_id,
        rule_type=event.rule_type,
        status=event.status,
        scheduled_at=event.scheduled_at,
        attempts=event.attempts,
        error_message=event.error_message,
        sent_at=event.sent_at,
        ack_at=event.ack_at,
        ack_by=event.ack_by,
        period_label=_period_label(event.payload),
        payload=event.payload,
        deliveries=[NotificationDeliveryRead.model_validate(item) for item in deliveries],
    )


def _billing_schedule_read(
    schedule: PartyBillingSchedule, party_name: str
) -> NotificationBillingScheduleRead:
    return NotificationBillingScheduleRead(
        id=schedule.id,
        party_id=schedule.party_id,
        party_name=party_name,
        contract_id=schedule.contract_id,
        day_of_month=schedule.day_of_month,
        frequency=schedule.frequency,
        anchor_month=schedule.anchor_month,
        amount_hint=schedule.amount_hint,
        notes=schedule.notes,
        active=schedule.active,
    )


async def _billing_schedule_read_with_lookup(
    session: AsyncSession, schedule: PartyBillingSchedule
) -> NotificationBillingScheduleRead:
    party = await session.get(Party, schedule.party_id)
    return _billing_schedule_read(schedule, party.name if party is not None else "")


@router.get(
    "/notifications/rules",
    response_model=list[NotificationRuleRead],
    summary="Listar las reglas de avisos internos del tenant",
)
async def get_notification_rules(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
) -> list[NotificationRuleRead]:
    """Siempre muestra las reglas implementadas, aunque el scheduler no haya corrido.

    ``admin.list_rules`` crea (apagadas) las que falten para este tenant; como
    es una lectura fuera de ``execute_idempotent``, el commit va aquí.
    """
    rules = await admin.list_rules(session, context)
    await session.commit()
    return [NotificationRuleRead.model_validate(rule) for rule in rules]


@router.put(
    "/notifications/rules/{rule_id}",
    response_model=NotificationRuleRead,
    summary="Editar una regla de avisos internos",
)
async def put_notification_rule(
    rule_id: uuid.UUID,
    data: NotificationRuleUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await admin.update_rule(session, context, rule_id, data)
        response = NotificationRuleRead.model_validate(entity).model_dump(
            mode="json", by_alias=True
        )
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.rules.update",
        idempotency_key=idempotency_key,
        request_payload={"rule_id": str(rule_id), **data.model_dump(mode="json")},
        action="notification_rule.updated",
        entity_type="notification_rule",
        callback=update,
    )


@router.get(
    "/notifications/templates/{rule_type}",
    response_model=NotificationTemplateRead,
    summary="Ver la plantilla de un tipo de aviso",
)
async def get_notification_template(
    rule_type: str,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
) -> NotificationTemplateRead:
    template, is_custom = await admin.get_template(session, context, rule_type)
    return NotificationTemplateRead(
        rule_type=template.rule_type,
        subject=template.subject,
        body=template.body,
        is_custom=is_custom,
    )


@router.put(
    "/notifications/templates/{rule_type}",
    response_model=NotificationTemplateRead,
    summary="Editar la plantilla de un tipo de aviso",
)
async def put_notification_template(
    rule_type: str,
    data: NotificationTemplateUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await admin.put_template(session, context, rule_type, data)
        response = NotificationTemplateRead(
            rule_type=entity.rule_type,
            subject=entity.subject,
            body=entity.body,
            is_custom=True,
        ).model_dump(mode="json", by_alias=True)
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.templates.update",
        idempotency_key=idempotency_key,
        request_payload={"rule_type": rule_type, **data.model_dump(mode="json")},
        action="notification_template.updated",
        entity_type="notification_template",
        callback=update,
    )


@router.delete(
    "/notifications/templates/{rule_type}",
    response_model=NotificationTemplateRead,
    summary="Volver la plantilla al valor por defecto del catálogo",
)
async def delete_notification_template(
    rule_type: str,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> NotificationTemplateRead:
    """Sin Idempotency-Key: borrar una fila que ya no existe es un no-op, no un error."""
    await admin.delete_template(session, context, rule_type)
    await session.commit()
    template, is_custom = await admin.get_template(session, context, rule_type)
    return NotificationTemplateRead(
        rule_type=template.rule_type,
        subject=template.subject,
        body=template.body,
        is_custom=is_custom,
    )


@router.post(
    "/notifications/templates/{rule_type}/preview",
    response_model=NotificationTemplatePreviewResult,
    summary="Previsualizar una plantilla con datos de ejemplo",
)
async def post_notification_template_preview(
    rule_type: str,
    data: NotificationTemplatePreviewRequest,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> NotificationTemplatePreviewResult:
    """Cómputo puro: no persiste nada, por eso no lleva Idempotency-Key."""
    subject, body_text, body_html = await admin.preview_template(
        session, context, rule_type, data
    )
    return NotificationTemplatePreviewResult(
        subject=subject, body_text=body_text, body_html=body_html
    )


@router.get(
    "/notifications/events",
    response_model=list[NotificationEventRead],
    summary="Bitácora de avisos programados",
)
async def get_notification_events(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
    status: str | None = None,
    rule_type: Annotated[str | None, Query(alias="ruleType")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = admin.DEFAULT_EVENTS_LIMIT,
) -> list[NotificationEventRead]:
    """El límite nunca pasa de ``MAX_EVENTS_LIMIT``, sin importar lo que pida el query param."""
    events = await admin.list_events(
        session,
        context,
        status=status,
        rule_type=rule_type,
        limit=min(limit, admin.MAX_EVENTS_LIMIT),
    )
    return [_event_read(event) for event in events]


@router.get(
    "/notifications/events/{event_id}",
    response_model=NotificationEventDetailRead,
    summary="Detalle de un aviso programado, con sus entregas",
)
async def get_notification_event(
    event_id: uuid.UUID,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
) -> NotificationEventDetailRead:
    event, deliveries = await admin.get_event_detail(session, context, event_id)
    return _event_detail_read(event, deliveries)


@router.post(
    "/notifications/events/{event_id}/ack",
    response_model=NotificationEventRead,
    summary="Registrar el acuse humano de un aviso",
)
async def post_notification_event_ack(
    event_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def ack() -> tuple[str, dict[str, object]]:
        event = await admin.ack_event(session, context, event_id)
        response = _event_read(event).model_dump(mode="json", by_alias=True)
        return str(event.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.events.ack",
        idempotency_key=idempotency_key,
        request_payload={"event_id": str(event_id)},
        action="notification_event.acknowledged",
        entity_type="notification_event",
        callback=ack,
    )


@router.post(
    "/notifications/events/{event_id}/resend",
    response_model=NotificationEventRead,
    summary="Reintentar el envío de un aviso",
)
async def post_notification_event_resend(
    event_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def resend() -> tuple[str, dict[str, object]]:
        event = await admin.resend_event(session, context, event_id)
        response = _event_read(event).model_dump(mode="json", by_alias=True)
        return str(event.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.events.resend",
        idempotency_key=idempotency_key,
        request_payload={"event_id": str(event_id)},
        action="notification_event.resent",
        entity_type="notification_event",
        callback=resend,
    )


@router.get(
    "/notifications/billing-schedules",
    response_model=list[NotificationBillingScheduleRead],
    summary="Listar el calendario de facturación por cliente",
)
async def get_billing_schedules(
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:read"))],
    party_id: Annotated[uuid.UUID | None, Query(alias="partyId")] = None,
    active: bool | None = None,
) -> list[NotificationBillingScheduleRead]:
    rows = await legal_commercial.list_billing_schedules(
        session, context, party_id=party_id, active=active
    )
    return [_billing_schedule_read(schedule, party_name) for schedule, party_name in rows]


@router.post(
    "/notifications/billing-schedules",
    response_model=NotificationBillingScheduleRead,
    status_code=201,
    summary="Crear un calendario de facturación para un cliente",
)
async def post_billing_schedule(
    data: NotificationBillingScheduleCreate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.create_billing_schedule(session, context, data)
        response = (
            await _billing_schedule_read_with_lookup(session, entity)
        ).model_dump(mode="json", by_alias=True)
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.billing_schedules.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="party_billing_schedule.created",
        entity_type="party_billing_schedule",
        callback=create,
    )


@router.put(
    "/notifications/billing-schedules/{schedule_id}",
    response_model=NotificationBillingScheduleRead,
    summary="Editar un calendario de facturación",
)
async def put_billing_schedule(
    schedule_id: uuid.UUID,
    data: NotificationBillingScheduleUpdate,
    idempotency_key: IdempotencyKey,
    session: Session,
    context: Annotated[AuthContext, Depends(require_scopes("notifications:write"))],
) -> dict[str, object]:
    async def update() -> tuple[str, dict[str, object]]:
        entity = await legal_commercial.update_billing_schedule(
            session, context, schedule_id, data
        )
        response = (
            await _billing_schedule_read_with_lookup(session, entity)
        ).model_dump(mode="json", by_alias=True)
        return str(entity.id), response

    return await execute_idempotent(
        session,
        context=context,
        operation="notifications.billing_schedules.update",
        idempotency_key=idempotency_key,
        request_payload={"schedule_id": str(schedule_id), **data.model_dump(mode="json")},
        action="party_billing_schedule.updated",
        entity_type="party_billing_schedule",
        callback=update,
    )


@router.post("/webhooks/brevo/{webhook_token}", include_in_schema=False)
async def receive_brevo_webhook(
    webhook_token: str,
    request: Request,
    session: Session,
) -> dict[str, int]:
    """Rebotes y quejas que reporta Brevo.

    Brevo no firma sus webhooks, asi que el secreto va en la ruta (mismo
    patron que el webhook de Evolution). Un token que no coincide responde 404
    y no 401: un endpoint publico no deberia confirmarle a nadie que existe.
    """
    if not webhooks.token_matches(webhook_token):
        raise HTTPException(status_code=404, detail="Not found")
    payload: Any = await request.json()
    applied = await webhooks.process_payload(session, payload=payload)
    await session.commit()
    return {"deliveriesUpdated": applied}


__all__ = ["router"]

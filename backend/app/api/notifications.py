"""Canal de avisos internos: estado, remitente, prueba y webhook (F2).

Deliberadamente pequeno. La configuracion completa de reglas, plantillas y la
bitacora es F4; aqui solo esta lo que F2 necesita para que alguien pueda
**verificar que el correo sale** antes de encender ninguna regla.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_scopes
from app.db.session import get_session
from app.integrations.notifications.email_sender import EmailMessage
from app.models.notifications import NotificationChannelAccount
from app.models.platform import Tenant
from app.schemas.notifications import (
    ChannelAccountRead,
    ChannelAccountUpdate,
    ChannelTestRequest,
    ChannelTestResult,
)
from app.services.notifications import channels, webhooks

router = APIRouter(tags=["notifications"])

Session = Annotated[AsyncSession, Depends(get_session)]


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

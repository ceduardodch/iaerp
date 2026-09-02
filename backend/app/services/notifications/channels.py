"""Que proveedor envia y con que cara sale el correo de cada empresa.

Con una sola cuenta Brevo de plataforma, la eleccion de proveedor es global
(hay clave o no la hay) y la identidad de remitente es por tenant.

El punto de diseno importante: **el estado se puede consultar**. Si falta la
clave o el remitente, eso se ve en ``channel_status`` en vez de descubrirse
porque los avisos "no llegan" y nadie sabe por que. Un modulo de correo que
falla en silencio es indistinguible de uno roto.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.notifications.brevo import BrevoEmailSender
from app.integrations.notifications.email_sender import EmailSender, StubEmailSender
from app.models.notifications import NotificationChannelAccount


@dataclass(frozen=True)
class SenderIdentity:
    """Con que remitente sale un aviso de este tenant."""

    email: str | None
    name: str
    reply_to: str | None


@dataclass(frozen=True)
class ChannelStatus:
    """Diagnostico legible del canal de correo, para la pantalla y el soporte."""

    provider: str
    platform_key_configured: bool
    sender_email: str | None
    sender_name: str
    reply_to: str | None
    ready: bool
    blocking_reason: str | None


def platform_sender_configured() -> bool:
    settings = get_settings()
    return settings.BREVO_API_KEY is not None and bool(settings.BREVO_SENDER_EMAIL)


def build_email_sender() -> EmailSender:
    """Proveedor activo.

    Sin ``BREVO_API_KEY`` devuelve el stub: el modulo sigue programando y
    registrando, pero marca ``STUBBED`` en vez de aparentar que envio. Esa es
    la diferencia que evita que un ambiente sin credenciales parezca uno sano.
    """
    settings = get_settings()
    if settings.BREVO_API_KEY is None:
        return StubEmailSender()
    return BrevoEmailSender(
        api_key=settings.BREVO_API_KEY.get_secret_value(),
        base_url=settings.BREVO_API_BASE_URL,
    )


async def _account(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> NotificationChannelAccount | None:
    account: NotificationChannelAccount | None = await session.scalar(
        select(NotificationChannelAccount).where(
            NotificationChannelAccount.tenant_id == tenant_id
        )
    )
    return account


async def resolve_sender_identity(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_name: str,
) -> SenderIdentity:
    """Remitente del tenant, cayendo al de plataforma cuando no configuro nada.

    El nombre visible por defecto es el de la empresa y no "IAERP": quien
    recibe el aviso trabaja en esa empresa, y ver su propio nombre en el
    remitente es lo que hace que el correo no parezca de un tercero.
    """
    settings = get_settings()
    account = await _account(session, tenant_id=tenant_id)
    name = (account.sender_name if account else None) or company_name
    return SenderIdentity(
        email=(account.sender_email if account else None) or settings.BREVO_SENDER_EMAIL,
        name=name or settings.BREVO_SENDER_NAME,
        reply_to=account.reply_to if account else None,
    )


async def channel_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_name: str,
) -> ChannelStatus:
    """Si el canal puede enviar de verdad, y si no, por que no."""
    settings = get_settings()
    identity = await resolve_sender_identity(
        session, tenant_id=tenant_id, company_name=company_name
    )
    key_configured = settings.BREVO_API_KEY is not None

    blocking_reason: str | None = None
    if not key_configured:
        blocking_reason = (
            "Falta BREVO_API_KEY en la configuracion del servidor: los avisos "
            "se registran pero no salen."
        )
    elif not identity.email:
        blocking_reason = (
            "Falta el correo de remitente (BREVO_SENDER_EMAIL o el del tenant) "
            "sobre un dominio verificado en Brevo."
        )

    return ChannelStatus(
        provider="BREVO" if key_configured else "STUB",
        platform_key_configured=key_configured,
        sender_email=identity.email,
        sender_name=identity.name,
        reply_to=identity.reply_to,
        ready=blocking_reason is None,
        blocking_reason=blocking_reason,
    )


__all__ = [
    "ChannelStatus",
    "SenderIdentity",
    "build_email_sender",
    "channel_status",
    "platform_sender_configured",
    "resolve_sender_identity",
]

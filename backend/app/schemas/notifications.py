"""Esquemas del canal de avisos internos (F2).

Ninguno de estos modelos transporta credenciales: con una sola cuenta Brevo de
plataforma, la clave vive en la configuracion del servidor y nunca entra ni
sale por HTTP. Lo que viaja aqui es identidad de remitente y diagnostico.
"""

from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.base import APIModel


class ChannelAccountUpdate(APIModel):
    """Con que cara salen los avisos de esta empresa."""

    sender_name: str | None = Field(default=None, max_length=200)
    # Solo sirve si el dominio esta autenticado en la cuenta Brevo de IAERP;
    # si no lo esta, el envio se rechaza. Por eso el default es el remitente
    # de plataforma y esto es opcional.
    sender_email: EmailStr | None = None
    reply_to: EmailStr | None = None


class ChannelAccountRead(APIModel):
    """Estado del canal, pensado para que un fallo se vea antes de enviar."""

    provider: str
    platform_key_configured: bool
    sender_email: str | None
    sender_name: str
    reply_to: str | None
    ready: bool
    blocking_reason: str | None


class ChannelTestRequest(APIModel):
    recipient: EmailStr


class ChannelTestResult(APIModel):
    provider: str
    status: str
    provider_message_id: str | None = None
    error_message: str | None = None


__all__ = [
    "ChannelAccountRead",
    "ChannelAccountUpdate",
    "ChannelTestRequest",
    "ChannelTestResult",
]

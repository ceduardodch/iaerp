"""Transporte de correo para los avisos internos (F1 del plan de avisos).

Contrato aparte del ``Notifier`` que ya vive en este paquete, a proposito:

- ``Notifier`` (``protocol.py``) manda recordatorios de **cobranza al cliente**
  y ademas escribe el ``CollectionReminder`` correspondiente.
- ``EmailSender`` (aqui) solo transporta. No toca la base: quien decide que se
  persiste es ``services/notifications/``. Asi el proveedor se cambia sin
  arrastrar reglas de negocio, que es justo el problema que tuvo cobranza.

La implementacion activa por defecto es ``StubEmailSender``: no abre red, para
que development y CI puedan ejercitar el flujo completo sin credenciales. El
``BrevoEmailSender`` real llega en F2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

EmailSendStatus = Literal["SENT", "STUBBED", "FAILED"]


@dataclass(frozen=True)
class EmailMessage:
    """Un correo ya renderizado, listo para salir.

    Llega renderizado a proposito: el transporte no conoce plantillas ni
    marcadores, solo entrega lo que le dan.
    """

    recipient: str
    subject: str
    body_text: str
    body_html: str
    sender_email: str | None = None
    sender_name: str | None = None
    # Con una sola cuenta de plataforma, el ``From`` sale del dominio
    # verificado de IAERP; el ``Reply-To`` es lo que devuelve la conversacion
    # a la empresa que corresponde.
    reply_to: str | None = None


@dataclass(frozen=True)
class EmailSendResult:
    """Resultado de un intento de envio.

    ``provider_message_id`` en ``None`` significa que el proveedor no devolvio
    identificador; nunca se inventa uno para rellenar el hueco, porque es la
    unica forma de cruzar despues un webhook de rebote con este envio.
    """

    provider: str
    status: EmailSendStatus
    provider_message_id: str | None = None
    error_message: str | None = None


class EmailSender(Protocol):
    """Proveedor de correo saliente para avisos internos."""

    @property
    def provider(self) -> str: ...

    async def send(self, message: EmailMessage) -> EmailSendResult: ...


class StubEmailSender:
    """No envia nada y lo dice: devuelve ``STUBBED``, nunca ``SENT``.

    La distincion importa. Si el stub devolviera ``SENT``, la bitacora de un
    ambiente de pruebas seria indistinguible de la de produccion y alguien
    terminaria creyendo que un aviso llego cuando nunca salio.

    Guarda lo que "envio" en ``sent`` para que las pruebas puedan afirmar sobre
    el contenido renderizado sin espiar la base.
    """

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    @property
    def provider(self) -> str:
        return "STUB"

    async def send(self, message: EmailMessage) -> EmailSendResult:
        self.sent.append(message)
        return EmailSendResult(provider="STUB", status="STUBBED")


__all__ = [
    "EmailMessage",
    "EmailSendResult",
    "EmailSendStatus",
    "EmailSender",
    "StubEmailSender",
]

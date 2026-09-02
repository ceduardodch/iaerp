"""Envio real de avisos internos por Brevo (F2 del plan de avisos).

Una sola cuenta de plataforma, decidida el 2026-09-02: la clave vive en la
configuracion del servidor (``BREVO_API_KEY``), nunca llega por HTTP ni se
guarda por tenant. Lo que si es por tenant es la **identidad de remitente**
(nombre visible y responder-a), que resuelve ``services/notifications``.

Dos decisiones que conviene no revertir:

- **``send`` no lanza excepciones por un fallo del proveedor.** Devuelve un
  ``EmailSendResult`` con ``FAILED``, para que un destinatario con el correo
  mal escrito no impida que el resto del equipo reciba el aviso.
- **El error se recorta y se limpia antes de guardarlo.** La respuesta de un
  proveedor puede arrastrar cabeceras o cuerpos con la clave; nada de eso
  puede terminar en ``NotificationDelivery.error_message`` ni en los logs.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.integrations.notifications.email_sender import EmailMessage, EmailSendResult

# Recorta el error a algo que quepa en la columna y no arrastre secretos.
_MAX_ERROR_LENGTH = 500
# Desde la palabra clave hasta el fin de linea. Intentar acotar el valor con
# ``\S+`` no alcanza: en `api-key': 'xkeysib-...'` las comillas cortan la
# coincidencia antes del secreto y la clave sobrevive. Ante la duda se borra
# de mas: nadie depura un incidente con el fragmento que quedo del error, pero
# una clave filtrada en la bitacora si es un problema real.
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[-_]?key|authorization|bearer|token|secret)\b.*",
)


def redact(value: str, *, secret: str | None = None) -> str:
    """Quita cualquier rastro de credencial del texto de error.

    ``secret`` es la clave concreta que uso este cliente. Borrarla por valor
    exacto es la unica defensa que no depende de adivinar como la escribio el
    proveedor en su respuesta.
    """
    if secret:
        value = value.replace(secret, "[REDACTED]")
    return _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)[:_MAX_ERROR_LENGTH]


class BrevoEmailSender:
    """Cliente del endpoint transaccional de Brevo (``POST /smtp/email``).

    Manda **un request por destinatario** en vez de un solo envio con varios
    ``to``. Cuesta mas llamadas, pero es lo que permite guardar un
    ``provider_message_id`` por persona y, con eso, cruzar despues un rebote
    con quien no recibio el aviso. Con destinatarios agrupados solo se sabria
    que "algo" reboto.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return "BREVO"

    def _payload(self, message: EmailMessage) -> dict[str, Any]:
        sender: dict[str, str] = {}
        if message.sender_email:
            sender["email"] = message.sender_email
        if message.sender_name:
            sender["name"] = message.sender_name
        payload: dict[str, Any] = {
            "sender": sender,
            "to": [{"email": message.recipient}],
            "subject": message.subject,
            "textContent": message.body_text,
            "htmlContent": message.body_html,
        }
        if message.reply_to:
            payload["replyTo"] = {"email": message.reply_to}
        return payload

    async def send(self, message: EmailMessage) -> EmailSendResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/smtp/email",
                    headers={
                        "api-key": self._api_key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    json=self._payload(message),
                )
        except httpx.HTTPError as exc:
            return EmailSendResult(
                provider=self.provider,
                status="FAILED",
                error_message=redact(f"{type(exc).__name__}: {exc}", secret=self._api_key),
            )

        if response.is_error:
            return EmailSendResult(
                provider=self.provider,
                status="FAILED",
                error_message=redact(
                    f"HTTP {response.status_code}: {response.text}", secret=self._api_key
                ),
            )

        return EmailSendResult(
            provider=self.provider,
            status="SENT",
            provider_message_id=_message_id(response),
        )


def _message_id(response: httpx.Response) -> str | None:
    """``messageId`` de la respuesta, o ``None`` si no vino.

    Nunca se inventa un identificador para rellenar el hueco: es la unica
    forma de cruzar un webhook de rebote con este envio, y uno falso haria
    creer que el cruce existe.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    value = body.get("messageId") or body.get("messageIds")
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value else None


__all__ = ["BrevoEmailSender", "redact"]

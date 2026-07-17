"""Contrato ``SRIClient`` para transmision y consulta de autorizacion SRI.

``docs/sprints/sprint-02.md`` (decision 7) define dos implementaciones futuras:
``SimulatorSRIClient`` (activa por defecto en development/test, ver
``simulator.py``) y un ``SoapSRIClient`` placeholder para un sprint futuro con
credenciales reales (no implementado aqui). Ambas deben respetar este mismo
``Protocol`` para que ``workers/sri_transmission.py`` no dependa de cual
implementacion esta activa.

Los estados devueltos (``ReceptionStatus``/``AuthorizationStatus``) son los
mismos nombres de estado que persiste ``SRITransmission``/``SalesDocument``
(ver ``models/billing.py``), para que el worker los use sin traducir un
vocabulario intermedio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

# Resultado de ``send_reception``: el SRI valida el XML de forma sincrona y
# solo indica si lo RECIBIO a validacion posterior o lo RECHAZO de inmediato
# (RETURNED, con motivo). Nunca autoriza en esta llamada.
ReceptionStatus = Literal["RECEIVED", "RETURNED"]

# Resultado de ``check_authorization``: el documento sigue pendiente, fue
# autorizado, fue rechazado en la validacion de autorizacion (NOT_AUTHORIZED,
# distinto del rechazo temprano RETURNED), o la consulta no obtuvo respuesta
# (timeout tecnico, no es un estado fiscal).
AuthorizationStatus = Literal[
    "PENDING_AUTHORIZATION",
    "AUTHORIZED",
    "NOT_AUTHORIZED",
    "TIMEOUT",
]


@dataclass(frozen=True)
class ReceptionResult:
    """Respuesta de ``send_reception``. ``messages`` son mensajes SRI crudos.

    ``messages`` sigue el formato ``[{"type": ..., "code": ..., "message": ...}]``
    para que se pueda persistir tal cual en ``SRITransmission.messages`` (JSON)
    sin transformacion adicional.
    """

    status: ReceptionStatus
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class AuthorizationResult:
    """Respuesta de ``check_authorization``.

    ``authorization_number`` y ``authorized_at`` solo se completan cuando
    ``status == "AUTHORIZED"``; en cualquier otro estado quedan ``None``.
    """

    status: AuthorizationStatus
    messages: list[dict[str, str]] = field(default_factory=list)
    authorization_number: str | None = None
    authorized_at: datetime | None = None


class SRIClient(Protocol):
    """Cliente de transmision SRI (real o simulado).

    Ninguna implementacion decide cuando reintentar ni actualiza
    ``SalesDocument``/``SRITransmission``: eso es responsabilidad exclusiva de
    ``workers/sri_transmission.py``, que es el unico llamador de este
    protocolo. Esto mantiene la logica de reconciliacion y reintentos en un
    solo lugar, sin duplicarla entre un cliente real futuro y el simulador.
    """

    async def send_reception(self, signed_xml: bytes, access_key: str) -> ReceptionResult: ...

    async def check_authorization(self, access_key: str) -> AuthorizationResult: ...


__all__ = [
    "AuthorizationResult",
    "AuthorizationStatus",
    "ReceptionResult",
    "ReceptionStatus",
    "SRIClient",
]

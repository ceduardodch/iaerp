"""Simulador SRI propio (in-memory) para Sprint 2 (no existe ambiente de
pruebas SRI real con credenciales en este entorno, ver
``docs/sprints/sprint-02.md`` decision 7).

``ScenarioStore`` es un dict en memoria, indexado por ``access_key``, con el
comportamiento a simular para esa clave. El comportamiento se fija
explicitamente por prueba/fixture (``set_scenario``), nunca al azar, para que
las pruebas sean reproducibles. El escenario por defecto (ninguno configurado)
es ``RECEIVED`` en la primera llamada a ``send_reception`` y ``AUTHORIZED`` en
la segunda consulta de autorizacion (``check_authorization``), que es el
camino feliz mas comun.

``SimulatorSRIClient`` implementa ``SRIClient`` (ver ``protocol.py``) hablando
in-process contra el ``ScenarioStore`` singleton de este modulo: no hace HTTP
real. El router FastAPI ``/sri-sim`` expone el MISMO store para
administracion desde pruebas de contrato/E2E (fijar el escenario de una clave
antes de emitir), pero el worker de transmision usa este cliente in-process
directamente, sin pasar por la red -- ambos comparten el mismo estado porque
``_STORE`` es un singleton de modulo.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.integrations.sri.protocol import AuthorizationResult, ReceptionResult

Behavior = Literal[
    "RECEIVED",
    "RETURNED",
    "AUTHORIZED",
    "NOT_AUTHORIZED",
    "TIMEOUT",
    "DUPLICATE_RESPONSE",
]

_DEFAULT_BEHAVIOR: Behavior = "RECEIVED"
_RETURNED_REASON_DEFAULT = "Comprobante no cumple validaciones de esquema (simulado)"
_NOT_AUTHORIZED_REASON_DEFAULT = "Numero de autorizacion no encontrado (simulado)"


@dataclass
class _AccessKeyState:
    """Estado simulado de una clave de acceso.

    ``behavior`` es el escenario configurado explicitamente para la clave
    (``None`` si nunca se configuro, en cuyo caso aplica el default). ``sent``
    cuenta cuantas veces se llamo ``send_reception`` (para detectar
    retransmision indebida en pruebas). ``authorization_checks`` cuenta
    ``check_authorization`` (el default autoriza en la segunda consulta).
    """

    behavior: Behavior | None = None
    reason: str | None = None
    sent: int = 0
    authorization_checks: int = 0
    authorization_number: str | None = None


class ScenarioStore:
    """Store en memoria, thread-safe, de escenarios por clave de acceso."""

    def __init__(self) -> None:
        self._states: dict[str, _AccessKeyState] = {}
        self._lock = threading.Lock()

    def set_scenario(
        self,
        access_key: str,
        behavior: Behavior,
        *,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            state = self._states.setdefault(access_key, _AccessKeyState())
            state.behavior = behavior
            state.reason = reason

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def _state_for(self, access_key: str) -> _AccessKeyState:
        return self._states.setdefault(access_key, _AccessKeyState())

    def send_reception(self, access_key: str) -> ReceptionResult:
        with self._lock:
            state = self._state_for(access_key)
            state.sent += 1
            behavior = state.behavior or _DEFAULT_BEHAVIOR

            if behavior == "TIMEOUT":
                raise TimeoutError(f"SRI simulator timed out for access key {access_key}")
            if behavior == "RETURNED":
                reason = state.reason or _RETURNED_REASON_DEFAULT
                return ReceptionResult(
                    status="RETURNED",
                    messages=[{"type": "ERROR", "code": "35", "message": reason}],
                )
            # RECEIVED, AUTHORIZED, NOT_AUTHORIZED and DUPLICATE_RESPONSE all
            # accept reception first; the terminal fiscal state is decided at
            # check_authorization time, mirroring the real SRI two-step flow
            # (recepcion sincrona, autorizacion asincrona).
            return ReceptionResult(status="RECEIVED", messages=[])

    def check_authorization(self, access_key: str) -> AuthorizationResult:
        with self._lock:
            state = self._state_for(access_key)
            state.authorization_checks += 1
            behavior = state.behavior or _DEFAULT_BEHAVIOR

            if behavior == "TIMEOUT":
                raise TimeoutError(f"SRI simulator timed out for access key {access_key}")
            if behavior == "RETURNED":
                # A returned (rejected at reception) document was never
                # accepted for authorization; nothing to check.
                raise ValueError(
                    f"Access key {access_key} was RETURNED at reception, "
                    "there is nothing to authorize"
                )
            if behavior == "NOT_AUTHORIZED":
                reason = state.reason or _NOT_AUTHORIZED_REASON_DEFAULT
                return AuthorizationResult(
                    status="NOT_AUTHORIZED",
                    messages=[{"type": "ERROR", "code": "52", "message": reason}],
                )
            if behavior in {"AUTHORIZED", "DUPLICATE_RESPONSE"}:
                if state.authorization_number is None:
                    state.authorization_number = access_key
                return AuthorizationResult(
                    status="AUTHORIZED",
                    messages=[],
                    authorization_number=state.authorization_number,
                    authorized_at=datetime.now(UTC),
                )
            # Default RECEIVED scenario: authorize on the second (or later)
            # authorization query, matching the documented default in
            # docs/sprints/sprint-02.md (decision 7).
            if state.authorization_checks >= 2:
                if state.authorization_number is None:
                    state.authorization_number = access_key
                return AuthorizationResult(
                    status="AUTHORIZED",
                    messages=[],
                    authorization_number=state.authorization_number,
                    authorized_at=datetime.now(UTC),
                )
            return AuthorizationResult(status="PENDING_AUTHORIZATION", messages=[])


# Singleton de proceso: compartido entre el cliente in-process y el router de
# administracion, para que fijar un escenario via HTTP (pruebas de contrato)
# afecte inmediatamente al worker que consume `SimulatorSRIClient`.
_STORE = ScenarioStore()


def get_store() -> ScenarioStore:
    return _STORE


@dataclass(frozen=True)
class SimulatorSRIClient:
    """Cliente ``SRIClient`` in-process contra el ``ScenarioStore`` singleton.

    No transmite nada por red: cumple el ``Protocol`` de ``protocol.py`` para
    que ``workers/sri_transmission.py`` no distinga entre esta implementacion
    y un futuro cliente SOAP real.
    """

    store: ScenarioStore = field(default_factory=get_store)

    async def send_reception(self, signed_xml: bytes, access_key: str) -> ReceptionResult:
        del signed_xml  # el simulador no valida contenido, solo el escenario fijado
        return self.store.send_reception(access_key)

    async def check_authorization(self, access_key: str) -> AuthorizationResult:
        return self.store.check_authorization(access_key)


# ---------------------------------------------------------------------------
# Router FastAPI de administracion del simulador ("/sri-sim").
#
# Montado en app/main.py SOLO si settings.SRI_SIMULATOR_ENABLED (default true
# en development/test, forbidden en release/production, ver
# app/core/config.py). No es un contrato SOAP real: son endpoints REST
# simplificados para fijar/inspeccionar el escenario de una clave desde
# pruebas de contrato o E2E.
# ---------------------------------------------------------------------------


class ScenarioRequest(BaseModel):
    access_key: str = Field(alias="accessKey", min_length=1, max_length=49)
    behavior: Behavior
    reason: str | None = None

    model_config = {"populate_by_name": True}


router = APIRouter(prefix="/sri-sim", tags=["sri-simulator"])


@router.post("/scenarios", status_code=204, include_in_schema=False)
async def set_scenario(data: ScenarioRequest) -> None:
    """Fija el escenario de una clave de acceso para la proxima transmision.

    Solo para pruebas: no exige autenticacion porque el router entero solo se
    monta cuando ``SRI_SIMULATOR_ENABLED`` esta activo (nunca en
    release/produccion, ver ``core/config.py``).
    """

    get_store().set_scenario(data.access_key, data.behavior, reason=data.reason)


@router.post("/reset", status_code=204, include_in_schema=False)
async def reset_scenarios() -> None:
    """Limpia todos los escenarios configurados (aislamiento entre pruebas)."""

    get_store().reset()


@router.get("/scenarios/{access_key}", include_in_schema=False)
async def get_scenario(access_key: str) -> dict[str, object]:
    state = get_store()._states.get(access_key)  # noqa: SLF001 - admin/debug endpoint
    if state is None:
        raise HTTPException(status_code=404, detail="No scenario configured for this access key")
    return {
        "accessKey": access_key,
        "behavior": state.behavior or _DEFAULT_BEHAVIOR,
        "sent": state.sent,
        "authorizationChecks": state.authorization_checks,
    }


__all__ = [
    "Behavior",
    "ScenarioStore",
    "SimulatorSRIClient",
    "get_store",
    "router",
]

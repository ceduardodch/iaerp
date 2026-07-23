"""Cliente SOAP real del SRI (recepcion + autorizacion offline).

Implementa el ``SRIClient`` (ver ``protocol.py``) hablando contra los web
services oficiales del SRI de Ecuador:

- **Recepcion** (``RecepcionComprobantesOffline``, operacion
  ``validarComprobante``): recibe el XML firmado en base64 y responde de forma
  SINCRONA si lo RECIBIO (``RECIBIDA``) o lo DEVOLVIO (``DEVUELTA``) por errores
  de esquema/firma.
- **Autorizacion** (``AutorizacionComprobantesOffline``, operacion
  ``autorizacionComprobante``): se consulta por clave de acceso hasta obtener
  ``AUTORIZADO`` / ``NO AUTORIZADO`` (o ``EN PROCESO`` = pendiente).

Ambientes SRI:
- ``"1"`` pruebas  -> ``celcer.sri.gob.ec``
- ``"2"`` produccion -> ``cel.sri.gob.ec``

Este cliente NO decide reintentos ni actualiza estado: eso es responsabilidad de
``workers/sri_transmission.py`` (unico llamador), que captura cualquier excepcion
tecnica (timeout/HTTP) y reprograma. Por eso aqui se deja PROPAGAR el error de
red; los estados fiscales se devuelven como ``ReceptionResult``/``AuthorizationResult``.
"""

from __future__ import annotations

import base64
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx

from app.integrations.sri.protocol import (
    AuthorizationResult,
    AuthorizationStatus,
    ReceptionResult,
)

# URLs oficiales por ambiente (path comun del WS de comprobantes electronicos).
_ENDPOINTS: dict[str, dict[str, str]] = {
    "1": {
        "reception": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline",
        "authorization": "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline",
    },
    "2": {
        "reception": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline",
        "authorization": "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline",
    },
}

_RECEPTION_ENVELOPE = (
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
    ' xmlns:ec="http://ec.gob.sri.ws.recepcion">'
    "<soapenv:Header/><soapenv:Body>"
    "<ec:validarComprobante><xml>{payload}</xml></ec:validarComprobante>"
    "</soapenv:Body></soapenv:Envelope>"
)

_AUTHORIZATION_ENVELOPE = (
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
    ' xmlns:ec="http://ec.gob.sri.ws.autorizacion">'
    "<soapenv:Header/><soapenv:Body>"
    "<ec:autorizacionComprobante>"
    "<claveAccesoComprobante>{access_key}</claveAccesoComprobante>"
    "</ec:autorizacionComprobante>"
    "</soapenv:Body></soapenv:Envelope>"
)


def _local(tag: str) -> str:
    """Nombre local de una etiqueta, ignorando el namespace (``{ns}tag`` -> ``tag``)."""
    return tag.rsplit("}", 1)[-1]


def _iter_local(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == name]


def _first_text(root: ET.Element, name: str) -> str | None:
    for el in root.iter():
        if _local(el.tag) == name and el.text is not None:
            return el.text.strip()
    return None


def _direct_text(element: ET.Element, name: str) -> str | None:
    """Texto del primer hijo DIRECTO con ese nombre local (no descendientes)."""
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _messages(node: ET.Element) -> list[dict[str, str]]:
    """Extrae los ``<mensaje>`` de un nodo al formato ``{type,code,message}``.

    OJO: el SRI nombra igual al CONTENEDOR ``<mensaje>`` y a su campo de texto
    interno ``<mensaje>``. Por eso se itera solo el hijo directo ``<mensaje>`` de
    cada ``<mensajes>`` y se leen sus campos por hijo directo, sin descender.
    """
    out: list[dict[str, str]] = []
    for mensajes in _iter_local(node, "mensajes"):
        for mensaje in mensajes:
            if _local(mensaje.tag) != "mensaje":
                continue
            code = _direct_text(mensaje, "identificador") or ""
            text = _direct_text(mensaje, "mensaje") or ""
            extra = _direct_text(mensaje, "informacionAdicional")
            tipo = _direct_text(mensaje, "tipo") or "ERROR"
            full = f"{text} — {extra}" if extra else text
            out.append({"type": tipo, "code": code, "message": full})
    return out


def _parse_authorization_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # El SRI a veces usa formatos no-ISO; no bloquear la autorizacion por eso.
        return None


class SoapSRIClient:
    """``SRIClient`` real contra los web services SOAP del SRI."""

    def __init__(
        self,
        *,
        environment: str = "1",
        reception_url: str | None = None,
        authorization_url: str | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        endpoints = _ENDPOINTS.get(environment, _ENDPOINTS["1"])
        self._reception_url = reception_url or endpoints["reception"]
        self._authorization_url = authorization_url or endpoints["authorization"]
        self._timeout = timeout
        # `transport` permite inyectar un httpx.MockTransport en pruebas sin
        # tocar la red; en produccion queda None (transporte HTTP por defecto).
        self._transport = transport

    async def send_reception(self, signed_xml: bytes, access_key: str) -> ReceptionResult:
        payload = base64.b64encode(signed_xml).decode("ascii")
        body = _RECEPTION_ENVELOPE.format(payload=payload).encode("utf-8")
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                self._reception_url,
                content=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            response.raise_for_status()
        return self._parse_reception(response.text)

    async def check_authorization(self, access_key: str) -> AuthorizationResult:
        body = _AUTHORIZATION_ENVELOPE.format(access_key=access_key).encode("utf-8")
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                self._authorization_url,
                content=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
            response.raise_for_status()
        return self._parse_authorization(response.text)

    @staticmethod
    def _parse_reception(xml_text: str) -> ReceptionResult:
        root = ET.fromstring(xml_text)
        estado = (_first_text(root, "estado") or "").upper()
        messages = _messages(root)
        if estado == "RECIBIDA":
            return ReceptionResult(status="RECEIVED", messages=messages)
        # DEVUELTA o cualquier otro estado = rechazo en recepcion.
        return ReceptionResult(status="RETURNED", messages=messages)

    @staticmethod
    def _parse_authorization(xml_text: str) -> AuthorizationResult:
        root = ET.fromstring(xml_text)
        autorizaciones = _iter_local(root, "autorizacion")
        if not autorizaciones:
            # Sin autorizaciones: el comprobante sigue en procesamiento.
            return AuthorizationResult(status="PENDING_AUTHORIZATION")

        autorizacion = autorizaciones[0]
        estado = (_first_text(autorizacion, "estado") or "").upper()
        messages = _messages(autorizacion)

        if estado == "AUTORIZADO":
            return AuthorizationResult(
                status="AUTHORIZED",
                messages=messages,
                authorization_number=_first_text(autorizacion, "numeroAutorizacion"),
                authorized_at=_parse_authorization_date(
                    _first_text(autorizacion, "fechaAutorizacion")
                ),
            )
        if estado in {"EN PROCESO", "EN PROCESAMIENTO", "PPR", "PROCESAMIENTO"}:
            return AuthorizationResult(status="PENDING_AUTHORIZATION", messages=messages)

        # NO AUTORIZADO / RECHAZADA / cualquier otro estado terminal negativo.
        status: AuthorizationStatus = "NOT_AUTHORIZED"
        return AuthorizationResult(status=status, messages=messages)


__all__ = ["SoapSRIClient"]

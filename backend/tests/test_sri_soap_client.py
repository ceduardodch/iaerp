"""Pruebas del cliente SOAP real del SRI (``app/integrations/sri/soap.py``).

Se mockea el transporte httpx con ``httpx.MockTransport`` (sin red real) y se
verifica el mapeo de las respuestas SOAP del SRI a los estados del ``SRIClient``
(``RECEIVED``/``RETURNED`` y ``AUTHORIZED``/``NOT_AUTHORIZED``/``PENDING``).

La certificacion real contra ``celcer.sri.gob.ec`` requiere el certificado .p12
y acceso a la red del SRI, y se corre en el despliegue, no aqui.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from app.integrations.sri.soap import SoapSRIClient


def _client(response_xml: str) -> SoapSRIClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=response_xml, headers={"Content-Type": "text/xml"})

    return SoapSRIClient(
        reception_url="https://mock.sri/reception",
        authorization_url="https://mock.sri/authorization",
        transport=httpx.MockTransport(handler),
    )


_RECEPTION_RECIBIDA = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:RespuestaRecepcionComprobante xmlns:ns2="http://ec.gob.sri.ws.recepcion">
<estado>RECIBIDA</estado><comprobantes/>
</ns2:RespuestaRecepcionComprobante></soap:Body></soap:Envelope>"""

_RECEPTION_DEVUELTA = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:RespuestaRecepcionComprobante xmlns:ns2="http://ec.gob.sri.ws.recepcion">
<estado>DEVUELTA</estado>
<comprobantes><comprobante><claveAcceso>1234567890</claveAcceso>
<mensajes><mensaje>
<identificador>35</identificador>
<mensaje>ARCHIVO NO CUMPLE ESTRUCTURA XML</mensaje>
<informacionAdicional>linea 3</informacionAdicional>
<tipo>ERROR</tipo>
</mensaje></mensajes>
</comprobante></comprobantes>
</ns2:RespuestaRecepcionComprobante></soap:Body></soap:Envelope>"""

_AUTH_AUTORIZADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:RespuestaAutorizacionComprobante xmlns:ns2="http://ec.gob.sri.ws.autorizacion">
<claveAccesoConsultada>1234567890</claveAccesoConsultada>
<numeroComprobantes>1</numeroComprobantes>
<autorizaciones><autorizacion>
<estado>AUTORIZADO</estado>
<numeroAutorizacion>2607202601</numeroAutorizacion>
<fechaAutorizacion>2026-07-22T10:30:00-05:00</fechaAutorizacion>
<ambiente>PRUEBAS</ambiente>
<comprobante>&lt;factura/&gt;</comprobante>
<mensajes/>
</autorizacion></autorizaciones>
</ns2:RespuestaAutorizacionComprobante></soap:Body></soap:Envelope>"""

_AUTH_NO_AUTORIZADO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:RespuestaAutorizacionComprobante xmlns:ns2="http://ec.gob.sri.ws.autorizacion">
<numeroComprobantes>1</numeroComprobantes>
<autorizaciones><autorizacion>
<estado>NO AUTORIZADO</estado>
<mensajes><mensaje>
<identificador>39</identificador>
<mensaje>FIRMA INVALIDA</mensaje>
<tipo>ERROR</tipo>
</mensaje></mensajes>
</autorizacion></autorizaciones>
</ns2:RespuestaAutorizacionComprobante></soap:Body></soap:Envelope>"""

_AUTH_EN_PROCESO = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:RespuestaAutorizacionComprobante xmlns:ns2="http://ec.gob.sri.ws.autorizacion">
<numeroComprobantes>0</numeroComprobantes>
<autorizaciones/>
</ns2:RespuestaAutorizacionComprobante></soap:Body></soap:Envelope>"""


async def test_reception_recibida_maps_to_received() -> None:
    result = await _client(_RECEPTION_RECIBIDA).send_reception(b"<factura/>", "1234567890")
    assert result.status == "RECEIVED"
    assert result.messages == []


async def test_reception_devuelta_maps_to_returned_with_messages() -> None:
    result = await _client(_RECEPTION_DEVUELTA).send_reception(b"<factura/>", "1234567890")
    assert result.status == "RETURNED"
    assert len(result.messages) == 1
    assert result.messages[0]["code"] == "35"
    assert result.messages[0]["type"] == "ERROR"
    assert "ESTRUCTURA XML" in result.messages[0]["message"]
    assert "linea 3" in result.messages[0]["message"]


async def test_authorization_autorizado() -> None:
    result = await _client(_AUTH_AUTORIZADO).check_authorization("1234567890")
    assert result.status == "AUTHORIZED"
    assert result.authorization_number == "2607202601"
    assert isinstance(result.authorized_at, datetime)
    assert result.authorized_at.year == 2026


async def test_authorization_no_autorizado() -> None:
    result = await _client(_AUTH_NO_AUTORIZADO).check_authorization("1234567890")
    assert result.status == "NOT_AUTHORIZED"
    assert result.authorization_number is None
    assert any("FIRMA INVALIDA" in m["message"] for m in result.messages)


async def test_authorization_en_proceso_is_pending() -> None:
    result = await _client(_AUTH_EN_PROCESO).check_authorization("1234567890")
    assert result.status == "PENDING_AUTHORIZATION"
    assert result.authorization_number is None


async def test_environment_selects_official_endpoints() -> None:
    pruebas = SoapSRIClient(environment="1")
    produccion = SoapSRIClient(environment="2")
    assert "celcer.sri.gob.ec" in pruebas._reception_url
    assert "cel.sri.gob.ec" in produccion._reception_url
    assert "celcer" not in produccion._reception_url

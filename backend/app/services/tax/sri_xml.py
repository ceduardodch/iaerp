"""Lectura de comprobantes autorizados del SRI (ADR 0012).

El portal entrega cada comprobante dentro de un sobre ``<autorizacion>`` que
contiene el XML real en un CDATA. Aqui se abre ese sobre y se traduce el
comprobante a una estructura neutra (``ParsedDocument``) que el resto del modulo
usa sin conocer el formato del SRI.

Solo se aceptan comprobantes **AUTORIZADOS**: un documento sin autorizacion no es
evidencia valida para declarar.

Todo el XML es de origen externo, asi que se parsea con ``defusedxml``
(bandit B314) igual que el cliente SOAP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring as _safe_fromstring  # type: ignore[import-untyped]
from fastapi import HTTPException

# Limite defensivo por archivo (los comprobantes del SRI son de pocos KB).
MAX_XML_BYTES = 2 * 1024 * 1024

# `codDoc` del SRI -> tipo de documento del modulo.
_DOC_TYPES = {
    "01": "FACTURA",
    "03": "LIQUIDACION",
    "04": "NOTA_CREDITO",
    "05": "NOTA_DEBITO",
    "07": "RETENCION",
}

# `codigoPorcentaje` del IVA -> tramo y tarifa nominal.
# Fuente: tabla 17 de la ficha tecnica del SRI. Las tarifas 12/14/15 conviven
# porque cada periodo declara con la vigente en su fecha de emision.
_IVA_BRACKETS: dict[str, tuple[str, Decimal]] = {
    "0": ("TARIFA_CERO", Decimal("0")),
    "2": ("GRAVADO", Decimal("12")),
    "3": ("GRAVADO", Decimal("14")),
    "4": ("GRAVADO", Decimal("15")),
    "5": ("GRAVADO", Decimal("5")),
    "6": ("NO_OBJETO", Decimal("0")),
    "7": ("EXENTO", Decimal("0")),
    "8": ("GRAVADO", Decimal("8")),
    "10": ("GRAVADO", Decimal("13")),
}

# `codigo` dentro de <retencion>: 1 = renta, 2 = IVA (tabla 21 del SRI).
# Se mantienen separadas porque el campo 609 del formulario 104 es SOLO IVA.
_RETENTION_KINDS = {"1": "RENTA", "2": "IVA"}


@dataclass
class ParsedTax:
    sri_tax_code: str
    tax_bracket: str
    rate: Decimal
    base_amount: Decimal
    tax_amount: Decimal


@dataclass
class ParsedRetention:
    kind: str
    sri_code: str
    percentage: Decimal
    base_amount: Decimal
    retained_amount: Decimal
    supporting_document_number: str | None = None


@dataclass
class ParsedDocument:
    """Comprobante del SRI en forma neutra, listo para persistir."""

    doc_type: str
    access_key: str
    authorization_number: str
    authorized_at: datetime | None
    issue_date: date
    issuer_identification: str
    issuer_name: str
    receiver_identification: str | None
    receiver_name: str | None
    establishment_code: str | None
    emission_point_code: str | None
    sequential: str | None
    subtotal: Decimal = Decimal("0.00")
    tax_total: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    payment_methods: list[str] = field(default_factory=list)
    taxes: list[ParsedTax] = field(default_factory=list)
    retentions: list[ParsedRetention] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(node: Element, path: str) -> str | None:
    """Texto de una ruta simple (``a/b/c``), ignorando namespaces."""
    current: Element | None = node
    for part in path.split("/"):
        if current is None:
            return None
        found = None
        for child in current:
            if _local(child.tag) == part:
                found = child
                break
        current = found
    if current is None or current.text is None:
        return None
    return current.text.strip() or None


def _children(node: Element, path: str) -> list[Element]:
    """Hijos directos que coinciden con la ultima parte de la ruta."""
    parts = path.split("/")
    nodes = [node]
    for part in parts:
        following: list[Element] = []
        for candidate in nodes:
            following.extend(child for child in candidate if _local(child.tag) == part)
        nodes = following
    return nodes


def _decimal(value: str | None, *, default: Decimal = Decimal("0.00")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return default


def parse_sri_date(value: str | None) -> date | None:
    """``dd/mm/yyyy`` (formato del SRI) a ``date``."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_authorization_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def open_authorization_envelope(xml_bytes: bytes) -> tuple[Element, str, datetime | None]:
    """Abre el sobre ``<autorizacion>`` y devuelve el comprobante interno.

    Rechaza cualquier comprobante que no este AUTORIZADO: sin autorizacion del
    SRI no es evidencia valida.
    """
    if not xml_bytes or len(xml_bytes) > MAX_XML_BYTES:
        raise HTTPException(status_code=422, detail="XML must be between 1 byte and 2 MB")
    try:
        envelope = _safe_fromstring(xml_bytes)
    except Exception as exc:  # noqa: BLE001 - cualquier XML invalido es 422
        raise HTTPException(status_code=422, detail="Invalid SRI XML") from exc

    if _local(envelope.tag) != "autorizacion":
        raise HTTPException(
            status_code=422, detail="XML must use the SRI authorization envelope"
        )
    if (_text(envelope, "estado") or "").upper() != "AUTORIZADO":
        raise HTTPException(status_code=422, detail="Document is not authorized by SRI")

    authorization_number = _text(envelope, "numeroAutorizacion")
    inner = _text(envelope, "comprobante")
    if not authorization_number or not inner:
        raise HTTPException(status_code=422, detail="XML lacks SRI authorization evidence")

    try:
        document = _safe_fromstring(inner.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Invalid embedded SRI receipt") from exc

    authorized_at = _parse_authorization_datetime(_text(envelope, "fechaAutorizacion"))
    return document, authorization_number, authorized_at


def _taxes_from_nodes(nodes: list[Element], *, base_tag: str, value_tag: str) -> list[ParsedTax]:
    taxes: list[ParsedTax] = []
    for node in nodes:
        code = _text(node, "codigoPorcentaje") or "0"
        bracket, nominal_rate = _IVA_BRACKETS.get(code, ("GRAVADO", Decimal("0")))
        # La tarifa declarada manda sobre la nominal: asi un periodo con 12% no
        # se reinterpreta con la tarifa vigente hoy.
        rate = _decimal(_text(node, "tarifa"), default=nominal_rate)
        taxes.append(
            ParsedTax(
                sri_tax_code=code,
                tax_bracket=bracket,
                rate=rate,
                base_amount=_decimal(_text(node, base_tag)),
                tax_amount=_decimal(_text(node, value_tag)),
            )
        )
    return taxes


def _parse_invoice_like(
    document: Element,
    *,
    doc_type: str,
    authorization_number: str,
    authorized_at: datetime | None,
    info_tag: str,
) -> ParsedDocument:
    issue_date = parse_sri_date(_text(document, f"{info_tag}/fechaEmision"))
    if issue_date is None:
        raise HTTPException(status_code=422, detail="Document has no valid issue date")

    taxes = _taxes_from_nodes(
        _children(document, f"{info_tag}/totalConImpuestos/totalImpuesto"),
        base_tag="baseImponible",
        value_tag="valor",
    )
    subtotal = _decimal(
        _text(document, f"{info_tag}/totalSinImpuestos"),
        default=sum((tax.base_amount for tax in taxes), Decimal("0.00")),
    )
    tax_total = sum((tax.tax_amount for tax in taxes), Decimal("0.00"))
    total = _decimal(
        _text(document, f"{info_tag}/importeTotal")
        or _text(document, f"{info_tag}/valorModificacion"),
        default=subtotal + tax_total,
    )
    payment_methods = list(
        dict.fromkeys(
            method
            for payment in _children(document, f"{info_tag}/pagos/pago")
            if (method := _text(payment, "formaPago")) is not None
        )
    )

    return ParsedDocument(
        doc_type=doc_type,
        access_key=_text(document, "infoTributaria/claveAcceso") or authorization_number,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
        issue_date=issue_date,
        issuer_identification=_text(document, "infoTributaria/ruc") or "",
        issuer_name=_text(document, "infoTributaria/razonSocial") or "",
        receiver_identification=_text(document, f"{info_tag}/identificacionComprador"),
        receiver_name=_text(document, f"{info_tag}/razonSocialComprador"),
        establishment_code=_text(document, "infoTributaria/estab"),
        emission_point_code=_text(document, "infoTributaria/ptoEmi"),
        sequential=_text(document, "infoTributaria/secuencial"),
        subtotal=subtotal,
        tax_total=tax_total,
        total=total,
        payment_methods=payment_methods,
        taxes=taxes,
    )


def _parse_retention(
    document: Element,
    *,
    authorization_number: str,
    authorized_at: datetime | None,
) -> ParsedDocument:
    issue_date = parse_sri_date(_text(document, "infoCompRetencion/fechaEmision"))
    if issue_date is None:
        raise HTTPException(status_code=422, detail="Retention has no valid issue date")

    retentions: list[ParsedRetention] = []

    def append_retention(item: Element, supporting_number: str | None) -> None:
        code = _text(item, "codigo") or ""
        kind = _RETENTION_KINDS.get(code)
        if kind is None:
            # Otros impuestos (p.ej. ISD) no entran al IVA mensual ni a la
            # conciliacion de renta; se omiten en vez de clasificarlos mal.
            return
        retentions.append(
            ParsedRetention(
                kind=kind,
                sri_code=_text(item, "codigoRetencion") or "",
                percentage=_decimal(_text(item, "porcentajeRetener")),
                base_amount=_decimal(_text(item, "baseImponible")),
                retained_amount=_decimal(_text(item, "valorRetenido")),
                supporting_document_number=supporting_number,
            )
        )

    for support in _children(document, "docsSustento/docSustento"):
        supporting_number = _text(support, "numDocSustento")
        for item in _children(support, "retenciones/retencion"):
            append_retention(item, supporting_number)

    # Los comprobantes de retención 1.0 guardan los rubros directamente en
    # ``impuestos``. Siguen siendo documentos SRI válidos y deben entrar al
    # mismo cálculo sin inventar ni transformar sus valores.
    if not retentions:
        for item in _children(document, "impuestos/impuesto"):
            append_retention(item, _text(item, "numDocSustento"))

    total_retained = sum((item.retained_amount for item in retentions), Decimal("0.00"))
    return ParsedDocument(
        doc_type="RETENCION",
        access_key=_text(document, "infoTributaria/claveAcceso") or authorization_number,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
        issue_date=issue_date,
        issuer_identification=_text(document, "infoTributaria/ruc") or "",
        issuer_name=_text(document, "infoTributaria/razonSocial") or "",
        receiver_identification=_text(
            document, "infoCompRetencion/identificacionSujetoRetenido"
        ),
        receiver_name=_text(document, "infoCompRetencion/razonSocialSujetoRetenido"),
        establishment_code=_text(document, "infoTributaria/estab"),
        emission_point_code=_text(document, "infoTributaria/ptoEmi"),
        sequential=_text(document, "infoTributaria/secuencial"),
        total=total_retained,
        retentions=retentions,
    )


def parse_receipt_element(
    document: Element,
    *,
    authorization_number: str,
    authorized_at: datetime | None,
) -> ParsedDocument:
    """Lee un comprobante YA extraido del sobre.

    Se expone aparte para poder reutilizarlo con los comprobantes que la propia
    entidad emitio: IAERP guarda su XML **firmado** (sin el sobre
    ``<autorizacion>``) y la autorizacion en ``SRITransmission``.
    """
    root_tag = _local(document.tag)
    cod_doc = _text(document, "infoTributaria/codDoc") or ""
    doc_type = _DOC_TYPES.get(cod_doc)

    if root_tag == "comprobanteRetencion" or doc_type == "RETENCION":
        return _parse_retention(
            document,
            authorization_number=authorization_number,
            authorized_at=authorized_at,
        )

    info_tags = {
        "factura": "infoFactura",
        "notaCredito": "infoNotaCredito",
        "notaDebito": "infoNotaDebito",
        "liquidacionCompra": "infoLiquidacionCompra",
    }
    info_tag = info_tags.get(root_tag)
    if info_tag is None or doc_type is None:
        raise HTTPException(status_code=422, detail=f"Unsupported SRI document: {root_tag}")

    return _parse_invoice_like(
        document,
        doc_type=doc_type,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
        info_tag=info_tag,
    )


def parse_authorized_document(xml_bytes: bytes) -> ParsedDocument:
    """Lee un comprobante autorizado del SRI (factura, NC, ND, liquidacion o retencion)."""
    document, authorization_number, authorized_at = open_authorization_envelope(xml_bytes)
    return parse_receipt_element(
        document,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
    )


def parse_signed_receipt(
    xml_bytes: bytes,
    *,
    authorization_number: str,
    authorized_at: datetime | None = None,
) -> ParsedDocument:
    """Lee un comprobante FIRMADO propio (sin el sobre ``<autorizacion>``).

    Es el formato que IAERP guarda como artefacto ``xml-signed`` al emitir. La
    autorizacion no viene en el archivo, asi que la aporta el llamador desde
    ``SRITransmission``.
    """
    if not xml_bytes or len(xml_bytes) > MAX_XML_BYTES:
        raise HTTPException(status_code=422, detail="XML must be between 1 byte and 2 MB")
    try:
        document = _safe_fromstring(xml_bytes)
    except Exception as exc:  # noqa: BLE001 - cualquier XML invalido es 422
        raise HTTPException(status_code=422, detail="Invalid signed receipt XML") from exc

    return parse_receipt_element(
        document,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
    )


__all__ = [
    "MAX_XML_BYTES",
    "ParsedDocument",
    "ParsedRetention",
    "ParsedTax",
    "open_authorization_envelope",
    "parse_authorized_document",
    "parse_receipt_element",
    "parse_signed_receipt",
    "parse_sri_date",
]

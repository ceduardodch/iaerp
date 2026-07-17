"""Generacion de XML SRI (factura y nota de credito, esquema 1.1.0).

Este modulo SOLO serializa: toma un ``SalesDocument`` y sus lineas ya
persistidos (con los totales calculados por ``fiscal_policy.py`` segun ADR
0008) y produce el arbol XML exigido por el esquema offline del SRI. Nunca
recalcula un monto -- si el documento y el XML difirieran, el SRI rechazaria
la factura con error 52 "Error en diferencias" en la fase de autorizacion,
que es exactamente lo que ADR 0008 previene al fijar una unica fuente de
calculo.

Referencias (ADR 0008, numeral 8.17 y formatos de factura/nota de credito):

- ``cantidad``/``precioUnitario``: hasta 6 decimales.
- Todo otro campo de valores: exactamente 2 decimales, punto decimal, sin
  notacion cientifica ni separador de miles.
- ``totalConImpuestos`` tiene un ``totalImpuesto`` por cada grupo
  ``(codigo, codigoPorcentaje)`` presente en el documento (no por linea).
- ``fechaEmision`` en formato ``dd/mm/aaaa``, zona horaria America/Guayaquil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from lxml import etree

from app.models.billing import SalesDocument, SalesDocumentLine
from app.models.masters import EmissionPoint, Establishment, Party

# Codigo de impuesto IVA en la tabla 16 de la Ficha Tecnica (unico impuesto
# modelado por IAERP en Sprint 2; retenciones y otros impuestos quedan fuera
# de alcance, ver docs/sprints/sprint-02.md "No incluido").
_IVA_TAX_CODE = "2"

# Version de esquema soportada: 1.1.0 admite 6 decimales en cantidad/precio
# unitario (ver ADR 0008, contexto).
_SCHEMA_VERSION = "1.1.0"

_INVOICE_ROOT_TAG = "factura"
_CREDIT_NOTE_ROOT_TAG = "notaCredito"

_IDENTIFICATION_TYPE_TO_SRI_CODE = {
    "RUC": "04",
    "CEDULA": "05",
    "PASSPORT": "06",
    "FINAL_CONSUMER": "07",
}
_FINAL_CONSUMER_IDENTIFICATION = "9999999999999"


@dataclass(frozen=True)
class SriXmlBuildResult:
    """Resultado de construir el XML: arbol y bytes serializados."""

    root: etree._Element
    xml_bytes: bytes


def _format_amount(value: Decimal) -> str:
    """Formatea un monto con exactamente 2 decimales, sin notacion cientifica."""

    quantized = value.quantize(Decimal("0.01"))
    return format(quantized, "f")


def _format_quantity_or_price(value: Decimal) -> str:
    """Formatea cantidad/precioUnitario con hasta 6 decimales (esquema 1.1.0)."""

    quantized = value.quantize(Decimal("0.000001"))
    return format(quantized, "f")


def _sub(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    element = etree.SubElement(parent, tag)
    if text is not None:
        element.text = text
    return element


def _build_tax_summary(lines: list[SalesDocumentLine]) -> etree._Element:
    """Construye ``totalConImpuestos`` con un ``totalImpuesto`` por grupo.

    Las lineas ya vienen agrupadas y cuantizadas por ``fiscal_policy.py``
    (``tax_sri_code``/``tax_rate`` snapshot por linea); aqui se re-agrupan
    para la serializacion XML SIN inventar una regla de calculo nueva: se
    aplica exactamente la misma formula de grupo que ``fiscal_policy.py``
    (ADR 0008 #5) -- ``baseImponible`` es la suma exacta de ``base_amount``
    de linea, y ``valor`` es ``quantize(baseImponible * tarifa / 100,
    0.01, HALF_UP)`` sobre esa base agregada. Deliberadamente NO es la suma
    de los ``tax_amount`` informativos por linea: el ADR es explicito en que
    esos valores pueden diferir en centavos (ver vector 3) y que el XML debe
    reflejar el total de grupo, no la suma de informativos.
    """

    base_by_group: dict[tuple[str, Decimal], Decimal] = {}
    for line in lines:
        key = (line.tax_sri_code, line.tax_rate)
        base_by_group[key] = base_by_group.get(key, Decimal("0.00")) + line.base_amount

    total_con_impuestos = etree.Element("totalConImpuestos")
    for (tax_sri_code, tax_rate), base_amount in sorted(base_by_group.items()):
        tax_amount = (base_amount * tax_rate / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total_impuesto = _sub(total_con_impuestos, "totalImpuesto")
        _sub(total_impuesto, "codigo", _IVA_TAX_CODE)
        _sub(total_impuesto, "codigoPorcentaje", tax_sri_code)
        _sub(total_impuesto, "baseImponible", _format_amount(base_amount))
        _sub(total_impuesto, "valor", _format_amount(tax_amount))
    return total_con_impuestos


def _build_detalles(lines: list[SalesDocumentLine]) -> etree._Element:
    detalles = etree.Element("detalles")
    for line in lines:
        detalle = _sub(detalles, "detalle")
        _sub(detalle, "codigoPrincipal", str(line.product_id) if line.product_id else "S/N")
        _sub(detalle, "descripcion", line.description)
        _sub(detalle, "cantidad", _format_quantity_or_price(line.quantity))
        _sub(detalle, "precioUnitario", _format_quantity_or_price(line.unit_price))
        _sub(detalle, "descuento", _format_amount(line.discount))
        _sub(detalle, "precioTotalSinImpuesto", _format_amount(line.base_amount))
        impuestos = _sub(detalle, "impuestos")
        impuesto = _sub(impuestos, "impuesto")
        _sub(impuesto, "codigo", _IVA_TAX_CODE)
        _sub(impuesto, "codigoPorcentaje", line.tax_sri_code)
        _sub(impuesto, "tarifa", _format_amount(line.tax_rate))
        _sub(impuesto, "baseImponible", _format_amount(line.base_amount))
        _sub(impuesto, "valor", _format_amount(line.tax_amount))
    return detalles


def _buyer_identification_code(identification_type: str) -> str:
    return _IDENTIFICATION_TYPE_TO_SRI_CODE.get(identification_type, "07")


def build_invoice_xml(
    *,
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    establishment: Establishment,
    emission_point: EmissionPoint,
    tenant_ruc: str,
    tenant_legal_name: str,
    tenant_commercial_address: str,
    buyer: Party,
    environment_code: Literal["1", "2"] = "1",
    emission_type_code: str = "1",
) -> SriXmlBuildResult:
    """Construye el XML de factura (esquema 1.1.0) desde datos ya persistidos.

    Todos los importes (``totalSinImpuestos``, ``totalConImpuestos``,
    ``importeTotal``, y por linea ``precioTotalSinImpuesto``) provienen de
    ``document``/``lines`` tal como los calculo y persistio
    ``services/billing.py`` con ``FiscalCalculationPolicy``; esta funcion no
    hace ninguna operacion aritmetica sobre montos, solo formatea y agrupa
    para la serializacion.
    """

    if document.access_key is None:
        raise ValueError("Cannot build invoice XML before the access key is assigned")
    if document.document_type != "INVOICE":
        raise ValueError(f"Expected an INVOICE document, got {document.document_type!r}")

    root = etree.Element(
        _INVOICE_ROOT_TAG, attrib={"id": "comprobante", "version": _SCHEMA_VERSION}
    )

    info_tributaria = _sub(root, "infoTributaria")
    _sub(info_tributaria, "ambiente", environment_code)
    _sub(info_tributaria, "tipoEmision", emission_type_code)
    _sub(info_tributaria, "razonSocial", tenant_legal_name)
    _sub(info_tributaria, "ruc", tenant_ruc)
    _sub(info_tributaria, "claveAcceso", document.access_key)
    _sub(info_tributaria, "codDoc", "01")
    _sub(info_tributaria, "estab", establishment.code)
    _sub(info_tributaria, "ptoEmi", emission_point.code)
    _sub(info_tributaria, "secuencial", document.sequential)
    _sub(info_tributaria, "dirMatriz", tenant_commercial_address)

    info_factura = _sub(root, "infoFactura")
    _sub(info_factura, "fechaEmision", document.issue_date.strftime("%d/%m/%Y"))
    _sub(info_factura, "dirEstablecimiento", establishment.address)
    _sub(info_factura, "obligadoContabilidad", "SI")
    _sub(
        info_factura,
        "tipoIdentificacionComprador",
        _buyer_identification_code(buyer.identification_type),
    )
    _sub(info_factura, "razonSocialComprador", buyer.name)
    _sub(
        info_factura,
        "identificacionComprador",
        buyer.identification_number
        if buyer.identification_type != "FINAL_CONSUMER"
        else _FINAL_CONSUMER_IDENTIFICATION,
    )
    _sub(info_factura, "totalSinImpuestos", _format_amount(document.subtotal))
    total_discount = sum((line.discount for line in lines), Decimal("0.00"))
    _sub(info_factura, "totalDescuento", _format_amount(total_discount))
    info_factura.append(_build_tax_summary(lines))
    _sub(info_factura, "propina", "0.00")
    _sub(info_factura, "importeTotal", _format_amount(document.total))
    _sub(info_factura, "moneda", document.currency)

    root.append(_build_detalles(lines))

    xml_bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    return SriXmlBuildResult(root=root, xml_bytes=xml_bytes)


def build_credit_note_xml(
    *,
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    establishment: Establishment,
    emission_point: EmissionPoint,
    tenant_ruc: str,
    tenant_legal_name: str,
    tenant_commercial_address: str,
    buyer: Party,
    related_invoice_sequential_full: str,
    related_invoice_issue_date: date,
    related_invoice_access_key: str,
    reason: str,
    environment_code: Literal["1", "2"] = "1",
    emission_type_code: str = "1",
) -> SriXmlBuildResult:
    """Construye el XML de nota de credito (esquema 1.1.0).

    ``related_invoice_sequential_full`` es el numero completo
    ``estab-ptoEmi-secuencial`` de la factura de sustento (``numDocModificado``
    en el esquema oficial). La tarifa de cada linea es la vigente a
    ``related_invoice_issue_date`` porque ``lines`` ya llega con el
    ``tax_sri_code``/``tax_rate`` congelados por ``services/billing.py`` al
    construir la NC (ADR 0008, seccion 5: "la tarifa de IVA correspondera a la
    fecha de emision del documento de sustento").
    """

    if document.access_key is None:
        raise ValueError("Cannot build credit note XML before the access key is assigned")
    if document.document_type != "CREDIT_NOTE":
        raise ValueError(f"Expected a CREDIT_NOTE document, got {document.document_type!r}")

    root = etree.Element(
        _CREDIT_NOTE_ROOT_TAG, attrib={"id": "comprobante", "version": _SCHEMA_VERSION}
    )

    info_tributaria = _sub(root, "infoTributaria")
    _sub(info_tributaria, "ambiente", environment_code)
    _sub(info_tributaria, "tipoEmision", emission_type_code)
    _sub(info_tributaria, "razonSocial", tenant_legal_name)
    _sub(info_tributaria, "ruc", tenant_ruc)
    _sub(info_tributaria, "claveAcceso", document.access_key)
    _sub(info_tributaria, "codDoc", "04")
    _sub(info_tributaria, "estab", establishment.code)
    _sub(info_tributaria, "ptoEmi", emission_point.code)
    _sub(info_tributaria, "secuencial", document.sequential)
    _sub(info_tributaria, "dirMatriz", tenant_commercial_address)

    info_nota_credito = _sub(root, "infoNotaCredito")
    _sub(info_nota_credito, "fechaEmision", document.issue_date.strftime("%d/%m/%Y"))
    _sub(info_nota_credito, "dirEstablecimiento", establishment.address)
    _sub(
        info_nota_credito,
        "tipoIdentificacionComprador",
        _buyer_identification_code(buyer.identification_type),
    )
    _sub(info_nota_credito, "razonSocialComprador", buyer.name)
    _sub(
        info_nota_credito,
        "identificacionComprador",
        buyer.identification_number
        if buyer.identification_type != "FINAL_CONSUMER"
        else _FINAL_CONSUMER_IDENTIFICATION,
    )
    _sub(info_nota_credito, "obligadoContabilidad", "SI")
    _sub(info_nota_credito, "codDocModificado", "01")
    _sub(info_nota_credito, "numDocModificado", related_invoice_sequential_full)
    _sub(
        info_nota_credito,
        "fechaEmisionDocSustento",
        related_invoice_issue_date.strftime("%d/%m/%Y"),
    )
    _sub(info_nota_credito, "totalSinImpuestos", _format_amount(document.subtotal))
    _sub(
        info_nota_credito,
        "valorModificacion",
        _format_amount(document.total),
    )
    _sub(info_nota_credito, "moneda", document.currency)
    info_nota_credito.append(_build_tax_summary(lines))
    _sub(info_nota_credito, "motivo", reason)

    root.append(_build_detalles(lines))

    xml_bytes = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    return SriXmlBuildResult(root=root, xml_bytes=xml_bytes)


__all__ = [
    "SriXmlBuildResult",
    "build_credit_note_xml",
    "build_invoice_xml",
]

"""Generacion del Anexo Transaccional Simplificado (ATS) — ADR 0012.

El orden de los nodos NO es libre: el SRI valida contra un XSD y rechaza el
archivo si un elemento aparece fuera de lugar. Este generador replica el orden de
dos ATS **aceptados** por el SRI (2025-07 y 2026-04), que son la referencia.

Detalles que causaron rechazos reales y que aqui quedan garantizados:

- La raiz del ATS es ``<iva>`` (no ``<ats>``) y la etiqueta del tipo de
  identificacion es ``TipoIDInformante`` (con "ID"), a diferencia del ADI, que usa
  ``<adi>`` y ``TipoIdInformante``.
- ``razonSocial`` va **antes** de ``Anio`` y ``Mes``.
- El mes se escribe con **dos digitos** (``01``, no ``1``).
- En ``detalleVentas``, ``tipoEmision`` precede a ``numeroComprobantes``.
- ``formasDePago`` es obligatorio cuando el comprobante supera el umbral del SRI.
- El ZIP debe contener **un solo XML en la raiz**: nada de ``__MACOSX`` ni
  archivos ocultos (comprimir desde el Finder de macOS los agrega y el SRI
  rechaza el archivo).
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

from app.services.tax.formatting import format_amount

# Sobre este monto el SRI exige declarar la forma de pago del comprobante.
PAYMENT_METHOD_THRESHOLD = Decimal("500.00")

# Orden exacto de <detalleCompras>, tomado de los ATS aceptados.
_PURCHASE_ORDER = (
    "codSustento",
    "tpIdProv",
    "idProv",
    "tipoComprobante",
    "parteRel",
    "fechaRegistro",
    "establecimiento",
    "puntoEmision",
    "secuencial",
    "fechaEmision",
    "autorizacion",
    "baseNoGraIva",
    "baseImponible",
    "baseImpGrav",
    "baseImpExe",
    "montoIce",
    "montoIva",
    "valRetBien10",
    "valRetServ20",
    "valorRetBienes",
    "valRetServ50",
    "valorRetServicios",
    "valRetServ100",
    "totbasesImpReemb",
)

# Orden exacto de <detalleVentas>. `tipoEmision` ANTES de `numeroComprobantes`.
_SALES_ORDER = (
    "tpIdCliente",
    "idCliente",
    "parteRelVtas",
    "tipoComprobante",
    "tipoEmision",
    "numeroComprobantes",
    "baseNoGraIva",
    "baseImponible",
    "baseImpGrav",
    "montoIva",
    "montoIce",
    "valorRetIva",
    "valorRetRenta",
)


@dataclass
class AtsPurchase:
    """Compra del periodo, ya conciliada."""

    supplier_identification: str
    supplier_identification_type: str = "01"
    support_code: str = "01"
    document_type: str = "01"
    related_party: str = "NO"
    establishment: str = "001"
    emission_point: str = "001"
    sequential: str = "000000001"
    issue_date: str = ""
    registration_date: str = ""
    authorization: str = ""
    base_no_iva: Decimal = Decimal("0.00")
    base_zero_rate: Decimal = Decimal("0.00")
    base_taxed: Decimal = Decimal("0.00")
    base_exempt: Decimal = Decimal("0.00")
    ice_amount: Decimal = Decimal("0.00")
    iva_amount: Decimal = Decimal("0.00")
    payment_methods: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.base_no_iva + self.base_zero_rate + self.base_taxed + self.iva_amount


@dataclass
class AtsSale:
    """Ventas agrupadas por cliente y tipo de comprobante."""

    customer_identification: str
    customer_identification_type: str = "04"
    related_party: str = "NO"
    document_type: str = "18"
    emission_type: str = "F"
    document_count: int = 1
    base_no_iva: Decimal = Decimal("0.00")
    base_zero_rate: Decimal = Decimal("0.00")
    base_taxed: Decimal = Decimal("0.00")
    iva_amount: Decimal = Decimal("0.00")
    ice_amount: Decimal = Decimal("0.00")
    withheld_iva: Decimal = Decimal("0.00")
    withheld_income_tax: Decimal = Decimal("0.00")
    payment_methods: list[str] = field(default_factory=list)


@dataclass
class AtsInput:
    identification: str
    legal_name: str
    year: int
    month: int
    establishment_count: str = "001"
    identification_type: str = "R"
    purchases: list[AtsPurchase] = field(default_factory=list)
    sales: list[AtsSale] = field(default_factory=list)
    sales_by_establishment: dict[str, Decimal] = field(default_factory=dict)


def _text_node(parent: Element, tag: str, value: str) -> None:
    SubElement(parent, tag).text = value


def format_month(month: int) -> str:
    """Mes con dos digitos. El SRI rechaza ``1``; espera ``01``."""
    return f"{month:02d}"


def _append_payment_methods(parent: Element, methods: list[str]) -> None:
    if not methods:
        return
    container = SubElement(parent, "formasDePago")
    for method in methods:
        _text_node(container, "formaPago", method)


def build_ats_xml(data: AtsInput) -> bytes:
    """Construye el XML del ATS respetando el orden de nodos aceptado."""
    root = Element("iva")

    # Cabecera: razonSocial va ANTES de Anio/Mes (a diferencia del ADI).
    _text_node(root, "TipoIDInformante", data.identification_type)
    _text_node(root, "IdInformante", data.identification)
    _text_node(root, "razonSocial", data.legal_name)
    _text_node(root, "Anio", str(data.year))
    _text_node(root, "Mes", format_month(data.month))
    _text_node(root, "numEstabRuc", data.establishment_count)
    total_sales = sum(
        (sale.base_no_iva + sale.base_zero_rate + sale.base_taxed for sale in data.sales),
        Decimal("0.00"),
    )
    _text_node(root, "totalVentas", format_amount(total_sales))
    _text_node(root, "codigoOperativo", "IVA")

    purchases = SubElement(root, "compras")
    for purchase in data.purchases:
        node = SubElement(purchases, "detalleCompras")
        values = {
            "codSustento": purchase.support_code,
            "tpIdProv": purchase.supplier_identification_type,
            "idProv": purchase.supplier_identification,
            "tipoComprobante": purchase.document_type,
            "parteRel": purchase.related_party,
            "fechaRegistro": purchase.registration_date or purchase.issue_date,
            "establecimiento": purchase.establishment,
            "puntoEmision": purchase.emission_point,
            "secuencial": purchase.sequential,
            "fechaEmision": purchase.issue_date,
            "autorizacion": purchase.authorization,
            "baseNoGraIva": format_amount(purchase.base_no_iva),
            "baseImponible": format_amount(purchase.base_zero_rate),
            "baseImpGrav": format_amount(purchase.base_taxed),
            "baseImpExe": format_amount(purchase.base_exempt),
            "montoIce": format_amount(purchase.ice_amount),
            "montoIva": format_amount(purchase.iva_amount),
            "valRetBien10": format_amount(Decimal("0.00")),
            "valRetServ20": format_amount(Decimal("0.00")),
            "valorRetBienes": format_amount(Decimal("0.00")),
            "valRetServ50": format_amount(Decimal("0.00")),
            "valorRetServicios": format_amount(Decimal("0.00")),
            "valRetServ100": format_amount(Decimal("0.00")),
            "totbasesImpReemb": format_amount(Decimal("0.00")),
        }
        for tag in _PURCHASE_ORDER:
            _text_node(node, tag, values[tag])

        payment_exterior = SubElement(node, "pagoExterior")
        _text_node(payment_exterior, "pagoLocExt", "01")
        _text_node(payment_exterior, "paisEfecPago", "NA")
        _text_node(payment_exterior, "aplicConvDobTrib", "NA")
        _text_node(payment_exterior, "pagExtSujRetNorLeg", "NA")

        # Obligatorio sobre el umbral; el SRI rechaza el anexo si falta.
        methods = purchase.payment_methods
        if not methods and purchase.total > PAYMENT_METHOD_THRESHOLD:
            methods = ["20"]
        _append_payment_methods(node, methods)

    sales = SubElement(root, "ventas")
    for sale in data.sales:
        node = SubElement(sales, "detalleVentas")
        values = {
            "tpIdCliente": sale.customer_identification_type,
            "idCliente": sale.customer_identification,
            "parteRelVtas": sale.related_party,
            "tipoComprobante": sale.document_type,
            "tipoEmision": sale.emission_type,
            "numeroComprobantes": str(sale.document_count),
            "baseNoGraIva": format_amount(sale.base_no_iva),
            "baseImponible": format_amount(sale.base_zero_rate),
            "baseImpGrav": format_amount(sale.base_taxed),
            "montoIva": format_amount(sale.iva_amount),
            "montoIce": format_amount(sale.ice_amount),
            "valorRetIva": format_amount(sale.withheld_iva),
            "valorRetRenta": format_amount(sale.withheld_income_tax),
        }
        for tag in _SALES_ORDER:
            _text_node(node, tag, values[tag])
        _append_payment_methods(node, sale.payment_methods or ["01"])

    by_establishment = SubElement(root, "ventasEstablecimiento")
    totals = data.sales_by_establishment or {"001": total_sales}
    for code, amount in totals.items():
        node = SubElement(by_establishment, "ventaEst")
        _text_node(node, "codEstab", code)
        _text_node(node, "ventasEstab", format_amount(amount))

    body = tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>{body}'.encode()


def ats_filename(data: AtsInput) -> str:
    """Nombre del archivo: ``AT`` + mes de dos digitos + anio."""
    return f"AT{format_month(data.month)}{data.year}.xml"


def build_ats_zip(xml_bytes: bytes, *, filename: str) -> bytes:
    """Empaqueta el ATS con **un solo XML en la raiz**.

    Se construye el ZIP explicitamente en vez de comprimir una carpeta: asi nunca
    se cuelan entradas como ``__MACOSX/._archivo.xml`` (las agrega el Finder de
    macOS) que hacen que el SRI rechace el anexo.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, xml_bytes)
    return buffer.getvalue()


def validate_ats_zip(data: bytes) -> list[str]:
    """Comprueba que el ZIP cumpla lo que exige el SRI. Devuelve los problemas."""
    problems: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["El archivo no es un ZIP valido."]

    names = archive.namelist()
    xml_at_root = [
        name
        for name in names
        if name.lower().endswith(".xml") and "/" not in name and not name.startswith(".")
    ]
    extra = [name for name in names if name not in xml_at_root]

    if len(xml_at_root) != 1:
        problems.append(
            f"El ZIP debe contener exactamente un XML en la raiz; contiene {len(xml_at_root)}."
        )
    if extra:
        problems.append(
            "El ZIP contiene archivos adicionales que el SRI rechaza: "
            + ", ".join(sorted(extra))
        )
    return problems


__all__ = [
    "PAYMENT_METHOD_THRESHOLD",
    "AtsInput",
    "AtsPurchase",
    "AtsSale",
    "ats_filename",
    "build_ats_xml",
    "build_ats_zip",
    "format_month",
    "validate_ats_zip",
]

"""RIDE (Representacion Impresa de Documento Electronico) en PDF con reportlab.

El RIDE se construye desde los MISMOS datos ya persistidos que ``sri_xml.py``
serializa (mismo ``SalesDocument``/lineas), nunca de un recalculo distinto:
esto evita que el PDF y el XML firmado muestren totales divergentes, que es
exactamente el riesgo que ``docs/sprints/sprint-02.md`` (decision 5) senala al
justificar reportlab con "layout tabular simple a partir de los mismos datos
que el XML".

``reportlab`` se eligio (ver mismo documento) por no requerir binarios
nativos como Pango/Cairo (WeasyPrint), lo que simplifica el Dockerfile.
"""

from __future__ import annotations

import io
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.billing import SalesDocument, SalesDocumentLine
from app.models.masters import EmissionPoint, Establishment, Party

_DOCUMENT_TYPE_LABEL = {
    "INVOICE": "FACTURA",
    "CREDIT_NOTE": "NOTA DE CREDITO",
}


def _format_amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _format_quantity_or_price(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _full_document_number(
    establishment: Establishment,
    emission_point: EmissionPoint,
    document: SalesDocument,
) -> str:
    return f"{establishment.code}-{emission_point.code}-{document.sequential}"


def _access_key_as_text_groups(access_key: str) -> str:
    """Representa la clave de acceso en grupos legibles (no normativo del SRI).

    El esquema oficial no exige un formato de agrupacion para la
    representacion textual, pero agrupar en bloques de 7 mejora la
    legibilidad humana del RIDE impreso, practica comun en implementaciones
    ecuatorianas existentes.
    """

    return " ".join(access_key[i : i + 7] for i in range(0, len(access_key), 7))


def _tax_summary(lines: list[SalesDocumentLine]) -> list[tuple[str, Decimal, Decimal]]:
    """Agrega base/impuesto por tarifa igual que ``sri_xml._build_tax_summary``.

    Duplicar esta agregacion (en vez de importar de ``sri_xml.py``) es
    deliberado: el RIDE es un documento de presentacion independiente del
    XML, pero ambos parten de los mismos ``base_amount``/``tax_rate`` ya
    persistidos por linea, por lo que el resultado es identico sin acoplar
    los dos modulos de serializacion.
    """

    base_by_group: dict[Decimal, Decimal] = {}
    for line in lines:
        base_by_group[line.tax_rate] = (
            base_by_group.get(line.tax_rate, Decimal("0.00")) + line.base_amount
        )

    return [
        (
            f"{tax_rate}%",
            base_amount,
            (base_amount * tax_rate / Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
        )
        for tax_rate, base_amount in sorted(base_by_group.items())
    ]


def build_ride_pdf(
    *,
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    establishment: Establishment,
    emission_point: EmissionPoint,
    tenant_ruc: str,
    tenant_legal_name: str,
    buyer: Party,
) -> bytes:
    """Genera el RIDE en PDF a partir de los mismos datos que el XML firmado.

    No recalcula ningun monto: usa ``document.subtotal``/``tax_total``/
    ``total`` y los campos de linea tal cual estan persistidos.
    """

    if document.access_key is None:
        raise ValueError("Cannot build RIDE before the access key is assigned")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    small_style = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)

    document_type_label = _DOCUMENT_TYPE_LABEL.get(
        document.document_type, document.document_type
    )
    full_number = _full_document_number(establishment, emission_point, document)

    story = []
    story.append(Paragraph(f"<b>{tenant_legal_name}</b>", styles["Title"]))
    story.append(Paragraph(f"RUC: {tenant_ruc}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>{document_type_label}</b> No. {full_number}", styles["Heading2"]))
    issue_date_text = document.issue_date.strftime("%d/%m/%Y")
    story.append(Paragraph(f"Fecha de emision: {issue_date_text}", styles["Normal"]))
    story.append(
        Paragraph(
            f"Clave de acceso: {document.access_key}",
            small_style,
        )
    )
    story.append(
        Paragraph(
            f"({_access_key_as_text_groups(document.access_key)})",
            small_style,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("<b>Comprador</b>", styles["Heading3"]))
    story.append(Paragraph(f"Nombre/Razon social: {buyer.name}", styles["Normal"]))
    story.append(
        Paragraph(
            f"Identificacion ({buyer.identification_type}): {buyer.identification_number}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("<b>Detalle</b>", styles["Heading3"]))
    line_rows: list[list[str]] = [
        ["Descripcion", "Cant.", "P. Unitario", "Descuento", "Subtotal"]
    ]
    for line in lines:
        line_rows.append(
            [
                line.description,
                _format_quantity_or_price(line.quantity),
                _format_quantity_or_price(line.unit_price),
                _format_amount(line.discount),
                _format_amount(line.base_amount),
            ]
        )
    line_column_widths = [7 * cm, 2 * cm, 2.7 * cm, 2.3 * cm, 2.5 * cm]
    line_table = Table(line_rows, hAlign="LEFT", colWidths=line_column_widths)
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(line_table)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("<b>Impuestos por tarifa</b>", styles["Heading3"]))
    tax_rows: list[list[str]] = [["Tarifa", "Base imponible", "Valor"]]
    for tax_label, base_amount, tax_amount in _tax_summary(lines):
        tax_rows.append([tax_label, _format_amount(base_amount), _format_amount(tax_amount)])
    tax_table = Table(tax_rows, hAlign="LEFT", colWidths=[3 * cm, 4 * cm, 4 * cm])
    tax_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story.append(tax_table)
    story.append(Spacer(1, 0.4 * cm))

    totals_rows = [
        ["Subtotal sin impuestos", _format_amount(document.subtotal)],
        ["Total impuestos", _format_amount(document.tax_total)],
        ["IMPORTE TOTAL", _format_amount(document.total)],
    ]
    totals_table = Table(totals_rows, hAlign="RIGHT", colWidths=[6 * cm, 3 * cm])
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    story.append(totals_table)

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_ride_pdf"]

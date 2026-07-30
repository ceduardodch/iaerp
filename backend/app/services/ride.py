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
from reportlab.lib.pagesizes import A4
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
        pagesize=A4,
        leftMargin=1.25 * cm,
        rightMargin=1.25 * cm,
        topMargin=1.1 * cm,
        bottomMargin=1.1 * cm,
    )
    styles = getSampleStyleSheet()
    navy = colors.HexColor("#16324F")
    blue = colors.HexColor("#1E5A88")
    mist = colors.HexColor("#EEF3F7")
    border = colors.HexColor("#C8D3DD")
    small_style = ParagraphStyle(
        "ride-small", parent=styles["Normal"], fontSize=7.5, leading=9.5, textColor=navy
    )
    body_style = ParagraphStyle(
        "ride-body", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=navy
    )
    title_style = ParagraphStyle(
        "ride-title",
        parent=styles["Title"],
        fontSize=17,
        leading=20,
        textColor=navy,
        spaceAfter=3,
    )

    document_type_label = _DOCUMENT_TYPE_LABEL.get(
        document.document_type, document.document_type
    )
    full_number = _full_document_number(establishment, emission_point, document)

    story = []
    issuer = Table(
        [
            [Paragraph(f"<b>{tenant_legal_name}</b>", title_style)],
            [Paragraph(f"RUC: {tenant_ruc}", body_style)],
            [Paragraph(f"Dirección matriz: {establishment.address}", small_style)],
        ],
        colWidths=[10.6 * cm],
    )
    issuer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    document_box = Table(
        [
            [Paragraph(f"<b>{document_type_label}</b>", body_style)],
            [Paragraph(f"No. {full_number}", body_style)],
            [Paragraph("CLAVE DE ACCESO", small_style)],
            [Paragraph(_access_key_as_text_groups(document.access_key), small_style)],
        ],
        colWidths=[7.1 * cm],
    )
    document_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), mist),
                ("BOX", (0, 0), (-1, -1), 0.75, navy),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    header = Table([[issuer, document_box]], colWidths=[10.8 * cm, 7.2 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(header)
    story.append(Spacer(1, 0.45 * cm))
    issue_date_text = document.issue_date.strftime("%d/%m/%Y")
    buyer_table = Table(
        [
            ["COMPRADOR", "IDENTIFICACIÓN", "FECHA DE EMISIÓN"],
            [buyer.name, buyer.identification_number, issue_date_text],
        ],
        colWidths=[9.2 * cm, 4.5 * cm, 4.3 * cm],
    )
    buyer_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), mist),
                ("TEXTCOLOR", (0, 0), (-1, 0), navy),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7),
                ("FONTSIZE", (0, 1), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.25, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(buyer_table)
    story.append(Spacer(1, 0.4 * cm))

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
    line_column_widths = [8.8 * cm, 2 * cm, 2.65 * cm, 2.45 * cm, 2.65 * cm]
    line_table = Table(line_rows, hAlign="LEFT", colWidths=line_column_widths)
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, border),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(line_table)
    story.append(Spacer(1, 0.4 * cm))

    tax_rows: list[list[str]] = [["Tarifa", "Base imponible", "Valor"]]
    for tax_label, base_amount, tax_amount in _tax_summary(lines):
        tax_rows.append([tax_label, _format_amount(base_amount), _format_amount(tax_amount)])
    tax_table = Table(tax_rows, hAlign="LEFT", colWidths=[3 * cm, 4 * cm, 4 * cm])
    tax_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), mist),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, border),
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
                ("BACKGROUND", (0, -1), (-1, -1), blue),
                ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, border),
            ]
        )
    )
    story.append(totals_table)

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_ride_pdf"]

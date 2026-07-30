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
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
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

_DOCUMENT_STATUS_LABEL = {
    "DRAFT": "Borrador",
    "READY": "Lista para emitir",
    "SIGNED": "Firmada y pendiente de envío",
    "RECEIVED": "Recibida por SRI",
    "PENDING_AUTHORIZATION": "En proceso de autorización",
    "AUTHORIZED": "Autorizada por SRI",
    "NOT_AUTHORIZED": "No autorizada por SRI",
    "REJECTED": "Rechazada por SRI",
    "FAILED": "Error de transmisión",
    "VOIDED": "Anulada",
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


def _paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    """Escapa el contenido externo antes de insertarlo en el markup de ReportLab."""

    from xml.sax.saxutils import escape

    return Paragraph(escape(value or "-"), style)


def _environment_label(environment_code: str) -> str:
    return "PRODUCCIÓN" if environment_code == "2" else "PRUEBAS"


def _document_status_label(status: str) -> str:
    """Texto legible, conservando el estado técnico en el modelo y API."""

    return _DOCUMENT_STATUS_LABEL.get(status, "Estado pendiente de clasificación")


def _format_authorized_at(value: datetime | None) -> str:
    if value is None:
        return "PENDIENTE DE AUTORIZACIÓN"
    return value.astimezone(ZoneInfo("America/Guayaquil")).strftime("%d/%m/%Y %H:%M:%S %Z")


def _ride_logo(logo_bytes: bytes | None) -> Image | None:
    if not logo_bytes:
        return None
    try:
        image_reader = ImageReader(io.BytesIO(logo_bytes))
        width, height = image_reader.getSize()
        scale = min((6.0 * cm) / width, (2.7 * cm) / height)
        return Image(io.BytesIO(logo_bytes), width=width * scale, height=height * scale)
    except Exception:  # noqa: BLE001 - una imagen inválida no debe impedir facturar
        return None


def build_ride_pdf(
    *,
    document: SalesDocument,
    lines: list[SalesDocumentLine],
    establishment: Establishment,
    emission_point: EmissionPoint,
    tenant_ruc: str,
    tenant_legal_name: str,
    buyer: Party,
    environment_code: str,
    logo_bytes: bytes | None = None,
) -> bytes:
    """Genera el RIDE en PDF a partir de los mismos datos que el XML firmado.

    No recalcula ningun monto: usa ``document.subtotal``/``tax_total``/
    ``total`` y los campos de linea tal cual estan persistidos.
    """

    if document.access_key is None:
        raise ValueError("Cannot build RIDE before the access key is assigned")

    if environment_code not in {"1", "2"}:
        raise ValueError("RIDE environment code must be '1' or '2'")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.1 * cm,
        rightMargin=1.1 * cm,
        topMargin=0.9 * cm,
        bottomMargin=0.9 * cm,
    )
    styles = getSampleStyleSheet()
    ink = colors.HexColor("#18233A")
    blue = colors.HexColor("#263A72")
    medium_gray = colors.HexColor("#D1D5DB")
    border = colors.HexColor("#80858D")
    tiny_style = ParagraphStyle(
        "ride-tiny", parent=styles["Normal"], fontSize=6.7, leading=8.2, textColor=ink
    )
    small_style = ParagraphStyle(
        "ride-small", parent=styles["Normal"], fontSize=7.8, leading=9.7, textColor=ink
    )
    body_style = ParagraphStyle(
        "ride-body", parent=styles["Normal"], fontSize=8.8, leading=11, textColor=ink
    )
    heading_style = ParagraphStyle(
        "ride-heading", parent=styles["Normal"], fontSize=10, leading=12, textColor=ink
    )
    brand_style = ParagraphStyle(
        "ride-brand", parent=styles["Title"], fontSize=26, leading=28, textColor=blue
    )
    document_type_style = ParagraphStyle(
        "ride-document", parent=styles["Normal"], fontSize=13, leading=16, textColor=ink
    )

    document_type_label = _DOCUMENT_TYPE_LABEL.get(document.document_type, document.document_type)
    full_number = _full_document_number(establishment, emission_point, document)
    authorization_number = document.authorization_number or "PENDIENTE DE AUTORIZACIÓN"

    issuer_brand = _ride_logo(logo_bytes) or Paragraph(
        "<b>B<span color='#A6C737'>2</span>B</b>", brand_style
    )
    issuer = Table(
        [
            [issuer_brand],
            [_paragraph(tenant_legal_name, heading_style)],
            [_paragraph(f"Emisor: {tenant_legal_name}", body_style)],
            [_paragraph(f"Matriz: {establishment.address}", body_style)],
            [Paragraph("Obligado a llevar contabilidad: SI", body_style)],
        ],
        colWidths=[10.3 * cm],
    )
    issuer.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)])
    )

    document_box = Table(
        [
            [Paragraph(f"R.U.C.: {tenant_ruc}", heading_style)],
            [Paragraph(f"<b>{document_type_label}</b>", document_type_style)],
            [Paragraph(f"No. {full_number}", body_style)],
            [Paragraph("NÚMERO DE AUTORIZACIÓN", small_style)],
            [_paragraph(authorization_number, tiny_style)],
            [
                Paragraph(
                    f"FECHA AUTORIZACIÓN: {_format_authorized_at(document.authorized_at)}",
                    small_style,
                )
            ],
            [Paragraph(f"AMBIENTE: {_environment_label(environment_code)}", small_style)],
            [Paragraph("EMISIÓN: NORMAL", small_style)],
            [Paragraph("CLAVE DE ACCESO", small_style)],
            [_paragraph(_access_key_as_text_groups(document.access_key), tiny_style)],
        ],
        colWidths=[8.1 * cm],
    )
    document_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("TOPPADDING", (0, 3), (-1, 3), 6),
                ("TOPPADDING", (0, 8), (-1, 8), 6),
            ]
        )
    )
    header = Table([[issuer, document_box]], colWidths=[10.5 * cm, 8.2 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    buyer_rows = [
        [
            _paragraph(f"COMPRADOR · Razón social / Nombres y apellidos: {buyer.name}", body_style),
            _paragraph(f"Identificación: {buyer.identification_number}", body_style),
        ],
        [
            _paragraph(f"Dirección: {buyer.address or '-'}", small_style),
            _paragraph(f"Fecha emisión: {document.issue_date.strftime('%d/%m/%Y')}", small_style),
        ],
    ]
    buyer_table = Table(buyer_rows, colWidths=[12.0 * cm, 6.7 * cm])
    buyer_table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                ("LINEBELOW", (0, -1), (-1, -1), 0.25, medium_gray),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    line_rows: list[list[object]] = [
        ["Cod.", "Cant.", "Descripción", "Precio unitario", "Descuento", "Precio total"]
    ]
    for line in lines:
        line_rows.append(
            [
                "-",
                _format_quantity_or_price(line.quantity),
                _paragraph(line.description, small_style),
                _format_amount(line.unit_price),
                _format_amount(line.discount),
                _format_amount(line.base_amount),
            ]
        )
    line_table = Table(
        line_rows,
        hAlign="LEFT",
        # Debe ocupar exactamente el mismo ancho que comprador y el bloque
        # inferior; así el borde derecho de totales coincide con el detalle.
        colWidths=[1.5 * cm, 1.5 * cm, 9.0 * cm, 2.35 * cm, 2.0 * cm, 2.35 * cm],
        repeatRows=1,
    )
    line_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), medium_gray),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, border),
                ("ALIGN", (0, 0), (1, -1), "CENTER"),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    additional_rows: list[list[object]] = [[Paragraph("Información adicional", body_style)]]
    if buyer.email:
        additional_rows.append([_paragraph(f"Email: {buyer.email}", small_style)])
    additional_rows.append(
        [Paragraph(f"Estado SRI: {_document_status_label(document.status)}", small_style)]
    )
    additional_table = Table(
        additional_rows,
        colWidths=[9.8 * cm],
        rowHeights=[0.75 * cm, *([0.62 * cm] * (len(additional_rows) - 1))],
    )
    additional_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    totals_rows: list[list[str]] = []
    for tax_label, base_amount, _tax_amount in _tax_summary(lines):
        totals_rows.append([f"SUBTOTAL {tax_label}", _format_amount(base_amount)])
    totals_rows.extend(
        [
            ["SUBTOTAL SIN IMPUESTOS", _format_amount(document.subtotal)],
            ["DESCUENTO", _format_amount(sum((line.discount for line in lines), Decimal("0.00")))],
            ["IVA", _format_amount(document.tax_total)],
            ["PROPINA", "0.00"],
            ["VALOR TOTAL", _format_amount(document.total)],
        ]
    )
    totals_table = Table(totals_rows, colWidths=[4.4 * cm, 2.6 * cm])
    totals_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, border),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), medium_gray),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    story = [
        header,
        Spacer(1, 0.45 * cm),
        buyer_table,
        Spacer(1, 0.55 * cm),
        line_table,
        Spacer(1, 0.55 * cm),
    ]
    lower = Table([[additional_table, totals_table]], colWidths=[11.7 * cm, 7.0 * cm])
    lower.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(lower)

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_ride_pdf"]

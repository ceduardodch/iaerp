"""Lectura del listado TXT de comprobantes del portal del SRI (ADR 0012).

El portal exporta un archivo separado por tabuladores y codificado en
**ISO-8859-1** (no UTF-8). Trae una fila por comprobante con sus totales, pero
no siempre con el detalle: las retenciones, por ejemplo, salen sin valores.

Regla del ADR 0012: lo que el TXT no permite afirmar NO se adivina. Esas filas se
devuelven marcadas como ``is_preliminary`` con el motivo, para que la interfaz
pida el XML correspondiente.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app.services.tax.sri_xml import parse_sri_date

MAX_TXT_BYTES = 10 * 1024 * 1024

# Encabezados del export del portal -> nombre interno.
_COLUMNS = {
    "RUC_EMISOR": "issuer_identification",
    "RAZON_SOCIAL_EMISOR": "issuer_name",
    "TIPO_COMPROBANTE": "document_label",
    "SERIE_COMPROBANTE": "series",
    "CLAVE_ACCESO": "access_key",
    "FECHA_AUTORIZACION": "authorized_at",
    "FECHA_EMISION": "issue_date",
    "IDENTIFICACION_RECEPTOR": "receiver_identification",
    "VALOR_SIN_IMPUESTOS": "subtotal",
    "IVA": "tax_total",
    "IMPORTE_TOTAL": "total",
    "NUMERO_DOCUMENTO_MODIFICADO": "modified_document",
}

# Etiqueta legible del portal -> tipo del modulo. Se compara sin tildes ni
# mayusculas porque el archivo llega en ISO-8859-1 y la etiqueta varia.
_DOCUMENT_TYPES = {
    "factura": "FACTURA",
    "notadecredito": "NOTA_CREDITO",
    "notadedebito": "NOTA_DEBITO",
    "comprobantederetencion": "RETENCION",
    "liquidaciondecompra": "LIQUIDACION",
    "liquidaciondecompradebienesyprestaciondeservicios": "LIQUIDACION",
}


@dataclass
class ParsedTxtRow:
    """Fila del TXT ya normalizada."""

    doc_type: str
    access_key: str
    issue_date: date
    issuer_identification: str
    issuer_name: str
    receiver_identification: str | None
    series: str | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    total: Decimal | None
    modified_document: str | None
    is_preliminary: bool
    preliminary_reason: str | None


def _normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    for accented, plain in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        lowered = lowered.replace(accented, plain)
    return "".join(char for char in lowered if char.isalnum())


def decode_portal_text(data: bytes) -> str:
    """Decodifica el TXT del portal.

    El archivo real viene en ISO-8859-1; se intenta UTF-8 primero por si alguna
    exportacion futura cambia, y se cae a latin-1, que nunca falla.
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("iso-8859-1")


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None


def parse_received_txt(data: bytes) -> list[ParsedTxtRow]:
    """Lee el listado de comprobantes recibidos/emitidos del portal."""
    if not data:
        raise HTTPException(status_code=422, detail="TXT file is empty")
    if len(data) > MAX_TXT_BYTES:
        raise HTTPException(status_code=422, detail="TXT file exceeds 10 MB")

    text = decode_portal_text(data)
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if not reader.fieldnames or "CLAVE_ACCESO" not in reader.fieldnames:
        raise HTTPException(
            status_code=422,
            detail="TXT does not look like an SRI receipt listing",
        )

    rows: list[ParsedTxtRow] = []
    for raw in reader:
        values = {
            internal: (raw.get(column) or "").strip()
            for column, internal in _COLUMNS.items()
        }
        access_key = values["access_key"]
        issue_date = parse_sri_date(values["issue_date"])
        if not access_key or issue_date is None:
            # Sin clave de acceso o sin fecha no se puede ubicar el comprobante
            # en un periodo; se omite en vez de inventar su ubicacion.
            continue

        doc_type = _DOCUMENT_TYPES.get(_normalize_label(values["document_label"]))
        subtotal = _optional_decimal(values["subtotal"])
        tax_total = _optional_decimal(values["tax_total"])
        total = _optional_decimal(values["total"])

        preliminary_reason: str | None = None
        if doc_type is None:
            doc_type = "FACTURA"
            preliminary_reason = (
                f"Tipo de comprobante no reconocido en el TXT: '{values['document_label']}'. "
                "Carga el XML para confirmarlo."
            )
        elif total is None or subtotal is None:
            preliminary_reason = (
                "El TXT no trae los valores de este comprobante. "
                "Carga el XML autorizado para obtener el detalle."
            )

        rows.append(
            ParsedTxtRow(
                doc_type=doc_type,
                access_key=access_key,
                issue_date=issue_date,
                issuer_identification=values["issuer_identification"],
                issuer_name=values["issuer_name"],
                receiver_identification=values["receiver_identification"] or None,
                series=values["series"] or None,
                subtotal=subtotal,
                tax_total=tax_total,
                total=total,
                modified_document=values["modified_document"] or None,
                is_preliminary=preliminary_reason is not None,
                preliminary_reason=preliminary_reason,
            )
        )
    return rows


__all__ = [
    "MAX_TXT_BYTES",
    "ParsedTxtRow",
    "decode_portal_text",
    "parse_received_txt",
]

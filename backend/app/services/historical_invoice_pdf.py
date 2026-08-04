"""Carga de facturas historicas respaldadas solo por su RIDE PDF.

Este flujo no reconstruye ni inventa un XML. Conserva el PDF original, crea
una venta visible para reportes operativos y usa el estado
``HISTORICAL_ISSUED`` para mantenerla fuera de ATS, transmision SRI, correo
fiscal y cartera.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.billing import (
    DocumentArtifact,
    SalesDocument,
    SalesDocumentLine,
    Sequence,
)
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.platform import Tenant
from app.services import access_key as access_key_service
from app.services import storage

MAX_HISTORICAL_PDF_BYTES = 5 * 1024 * 1024
_MONEY_QUANTUM = Decimal("0.01")
_RATE = Decimal("15.000000")
_HISTORICAL_STATUS = "HISTORICAL_ISSUED"


@dataclass(frozen=True)
class HistoricalInvoicePdf:
    issuer_ruc: str
    establishment_code: str
    emission_point_code: str
    sequential: str
    access_key: str
    authorization_number: str
    authorized_at: datetime
    issue_date: date
    customer_identification: str
    product_code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _money(raw: str, *, label: str) -> Decimal:
    try:
        return Decimal(raw.strip().replace(",", "")).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError) as error:
        raise _invalid(f"No se pudo leer {label} del PDF") from error


def _match(text: str, pattern: str, *, label: str, flags: int = 0) -> str:
    found = re.search(pattern, text, flags)
    if found is None:
        raise _invalid(f"El PDF no contiene {label}")
    return found.group(1).strip()


def _amount_after(text: str, label: str) -> Decimal:
    raw = _match(
        text,
        rf"{re.escape(label)}\s*\n\s*([0-9]+(?:[.,][0-9]{{2}})?)",
        label=label,
        flags=re.IGNORECASE,
    )
    return _money(raw, label=label)


def _extract_text(pdf_data: bytes) -> str:
    if (
        not pdf_data.startswith(b"%PDF-")
        or b"%%EOF" not in pdf_data[-2048:]
        or len(pdf_data) > MAX_HISTORICAL_PDF_BYTES
    ):
        raise _invalid("El archivo debe ser un PDF completo de hasta 5 MB")
    try:
        reader = PdfReader(io.BytesIO(pdf_data), strict=False)
        if reader.is_encrypted:
            raise _invalid("El PDF historico no puede estar cifrado")
        if not 1 <= len(reader.pages) <= 3:
            raise _invalid("El RIDE historico debe tener entre una y tres paginas")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, OSError, ValueError) as error:
        raise _invalid("No se pudo leer el PDF historico") from error
    if not text.strip() or len(text) > 200_000:
        raise _invalid("El PDF historico no contiene texto legible")
    return text


def _line_detail(text: str, subtotal: Decimal) -> tuple[str, str, Decimal, Decimal, Decimal]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        header_index = lines.index("Precio Total")
        subtotal_index = lines.index("SUBTOTAL 15%", header_index + 1)
    except ValueError as error:
        raise _invalid("El PDF no tiene el detalle esperado de una factura Sky") from error
    values = lines[header_index + 1 : subtotal_index]
    if len(values) < 6:
        raise _invalid("El detalle del PDF esta incompleto")
    product_code, quantity_raw = values[0], values[1]
    unit_price_raw, discount_raw, line_total_raw = values[-3:]
    description = " ".join(values[2:-3]).strip()
    try:
        quantity = Decimal(quantity_raw)
        unit_price = Decimal(unit_price_raw)
        discount = Decimal(discount_raw).quantize(_MONEY_QUANTUM)
    except InvalidOperation as error:
        raise _invalid("El detalle del PDF contiene cantidades invalidas") from error
    if quantity <= 0 or unit_price < 0 or discount < 0 or not description:
        raise _invalid("El detalle del PDF no es valido")
    line_total = _money(line_total_raw, label="total de la linea")
    calculated = (quantity * unit_price - discount).quantize(
        _MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    if calculated != line_total or line_total != subtotal:
        raise _invalid("La linea del PDF no cuadra con el subtotal")
    return product_code[:80], description[:500], quantity, unit_price, discount


def parse_historical_invoice_pdf(pdf_data: bytes) -> HistoricalInvoicePdf:
    """Extrae y cruza los datos visibles del RIDE sin atribuirle un XML."""

    text = _extract_text(pdf_data)
    issuer_ruc = _match(text, r"R\.U\.C\.:\s*(\d{13})", label="RUC del emisor")
    full_number = _match(
        text,
        r"No\.\s*(\d{3}-\d{3}-\d{9})",
        label="numero de factura",
    )
    establishment_code, emission_point_code, sequential = full_number.split("-")
    authorization_number = _match(
        text,
        r"N[ÚU]MERO DE AUTORIZACI[ÓO]N\s*(\d{49})",
        label="numero de autorizacion",
    )
    access_key = _match(
        text,
        r"CLAVE DE ACCESO\s*(\d{49})",
        label="clave de acceso",
    )
    try:
        authorized_at = datetime.fromisoformat(
            _match(
                text,
                r"FECHA AUTORIZACI[ÓO]N:\s*([^\n]+)",
                label="fecha de autorizacion",
            )
        )
        issue_date = datetime.strptime(
            _match(
                text,
                r"Fecha Emisi[óo]n:\s*(\d{2}/\d{2}/\d{4})",
                label="fecha de emision",
            ),
            "%d/%m/%Y",
        ).date()
    except ValueError as error:
        raise _invalid("Las fechas del PDF no tienen el formato esperado") from error
    customer_identification = _match(
        text,
        r"Identificaci[óo]n:\s*(\d{10,13})",
        label="identificacion del cliente",
    )
    subtotal_15 = _amount_after(text, "SUBTOTAL 15%")
    subtotal_0 = _amount_after(text, "SUBTOTAL 0%")
    subtotal_not_subject = _amount_after(text, "SUBTOTAL No Obj. IVA")
    subtotal_exempt = _amount_after(text, "SUBTOTAL Exento IVA")
    subtotal = _amount_after(text, "SUBTOTAL SIN IMPUESTOS")
    total_discount = _amount_after(text, "DESCUENTO")
    ice = _amount_after(text, "ICE")
    tax_total = _amount_after(text, "IVA 15%")
    tip = _amount_after(text, "PROPINA")
    total = _amount_after(text, "VALOR TOTAL")

    if not access_key_service.verify_access_key(access_key):
        raise _invalid("La clave de acceso del PDF no supera el digito verificador")
    expected_prefix = (
        issue_date.strftime("%d%m%Y")
        + "01"
        + issuer_ruc
        + "2"
        + establishment_code
        + emission_point_code
        + sequential
    )
    if not access_key.startswith(expected_prefix) or access_key != authorization_number:
        raise _invalid("La clave del PDF no coincide con sus datos de factura y autorizacion")
    if subtotal_0 != 0 or subtotal_not_subject != 0 or subtotal_exempt != 0:
        raise _invalid("Este flujo historico admite por ahora facturas con una sola base IVA 15%")
    if total_discount != 0 or ice != 0 or tip != 0 or subtotal_15 != subtotal:
        raise _invalid("Los totales especiales del PDF requieren revision manual")
    expected_tax = (subtotal * Decimal("0.15")).quantize(
        _MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )
    if tax_total != expected_tax or subtotal + tax_total != total:
        raise _invalid("El subtotal, IVA y total del PDF no cuadran")
    product_code, description, quantity, unit_price, discount = _line_detail(text, subtotal)
    return HistoricalInvoicePdf(
        issuer_ruc=issuer_ruc,
        establishment_code=establishment_code,
        emission_point_code=emission_point_code,
        sequential=sequential,
        access_key=access_key,
        authorization_number=authorization_number,
        authorized_at=authorized_at,
        issue_date=issue_date,
        customer_identification=customer_identification,
        product_code=product_code,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        discount=discount,
        subtotal=subtotal,
        tax_total=tax_total,
        total=total,
    )


async def _advance_sequence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    sequential: str,
) -> None:
    sequence = await session.scalar(
        select(Sequence)
        .where(
            Sequence.tenant_id == tenant_id,
            Sequence.document_type == "INVOICE",
            Sequence.establishment_id == establishment_id,
            Sequence.emission_point_id == emission_point_id,
        )
        .with_for_update()
    )
    next_value = int(sequential) + 1
    if sequence is None:
        session.add(
            Sequence(
                tenant_id=tenant_id,
                document_type="INVOICE",
                establishment_id=establishment_id,
                emission_point_id=emission_point_id,
                next_value=next_value,
            )
        )
    elif sequence.next_value < next_value:
        sequence.next_value = next_value


async def create_historical_invoice_from_pdf(
    session: AsyncSession,
    context: AuthContext,
    *,
    pdf_data: bytes,
) -> SalesDocument:
    """Crea una venta historica de reporte, sin cartera ni efecto tributario."""

    parsed = parse_historical_invoice_pdf(pdf_data)
    tenant = await session.get(Tenant, context.tenant_id)
    if tenant is None or tenant.ruc != parsed.issuer_ruc:
        raise _invalid("El RUC emisor del PDF no coincide con la empresa activa")
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == context.tenant_id,
            Party.identification_number == parsed.customer_identification,
        )
    )
    if party is None:
        raise _invalid("El cliente del PDF debe existir antes de cargar la factura historica")
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.tenant_id == context.tenant_id,
            Establishment.code == parsed.establishment_code,
        )
    )
    if establishment is None:
        raise _invalid("El establecimiento del PDF no existe en IAERP")
    emission_point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.tenant_id == context.tenant_id,
            EmissionPoint.establishment_id == establishment.id,
            EmissionPoint.code == parsed.emission_point_code,
        )
    )
    if emission_point is None:
        raise _invalid("El punto de emision del PDF no existe en IAERP")
    existing = await session.scalar(
        select(SalesDocument).where(
            (SalesDocument.access_key == parsed.access_key)
            | (
                (SalesDocument.tenant_id == context.tenant_id)
                & (SalesDocument.document_type == "INVOICE")
                & (SalesDocument.establishment_id == establishment.id)
                & (SalesDocument.emission_point_id == emission_point.id)
                & (SalesDocument.sequential == parsed.sequential)
            )
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="La factura historica ya existe en IAERP")

    pdf_sha256 = hashlib.sha256(pdf_data).hexdigest()
    document = SalesDocument(
        tenant_id=context.tenant_id,
        document_type="INVOICE",
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=parsed.sequential,
        access_key=parsed.access_key,
        party_id=party.id,
        issue_date=parsed.issue_date,
        status=_HISTORICAL_STATUS,
        currency="USD",
        subtotal=parsed.subtotal,
        tax_total=parsed.tax_total,
        total=parsed.total,
        fiscal_policy_version="historical-pdf-v1",
        reason="Factura historica respaldada por RIDE PDF; XML no disponible.",
        authorization_number=parsed.authorization_number,
        authorized_at=parsed.authorized_at,
        commercial_snapshot={
            "source": "RIDE_PDF",
            "historical": True,
            "reporting_only": True,
            "xml_available": False,
            "pdf_sha256": pdf_sha256,
        },
        collection_enabled=False,
    )
    session.add(document)
    await session.flush()
    session.add(
        SalesDocumentLine(
            tenant_id=context.tenant_id,
            sales_document_id=document.id,
            line_number=1,
            product_id=None,
            product_code=parsed.product_code,
            description=parsed.description,
            quantity=parsed.quantity,
            unit_price=parsed.unit_price,
            discount=parsed.discount,
            base_amount=parsed.subtotal,
            tax_sri_code="4",
            tax_rate=_RATE,
            tax_amount=parsed.tax_total,
        )
    )
    upload = await storage.upload_artifact(
        tenant_id=str(context.tenant_id),
        document_id=str(document.id),
        artifact_type="ride-pdf",
        version=1,
        data=pdf_data,
    )
    session.add(
        DocumentArtifact(
            tenant_id=context.tenant_id,
            sales_document_id=document.id,
            artifact_type="ride-pdf",
            object_key=upload.object_key,
            sha256=upload.sha256,
            version=1,
        )
    )
    await _advance_sequence(
        session,
        tenant_id=context.tenant_id,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=parsed.sequential,
    )
    await session.flush()
    return document


__all__ = [
    "MAX_HISTORICAL_PDF_BYTES",
    "HistoricalInvoicePdf",
    "create_historical_invoice_from_pdf",
    "parse_historical_invoice_pdf",
]

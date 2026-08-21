"""Ingesta de evidencia: de archivo a ``FiscalDocument`` (ADR 0012).

Convierte la evidencia ya custodiada (``TaxEvidence``) en documentos fiscales
consultables. Reglas que aplica:

- El periodo se resuelve por la **fecha real de emision** del comprobante, nunca
  por el nombre del archivo o de la carpeta (un archivo llamado "Diciembre 2025"
  puede contener comprobantes de noviembre; paso en los datos reales).
- Un comprobante se identifica por su clave de acceso: reprocesar la misma
  evidencia actualiza, no duplica.
- El XML manda sobre el TXT. Si un comprobante ya existe con detalle del XML, una
  fila del TXT no lo degrada a preliminar.
- Lo que no se puede afirmar queda ``is_preliminary`` con su motivo; no se
  inventan valores.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxEvidence
from app.services import storage
from app.services.tax import periods as periods_service
from app.services.tax.sri_xml import ParsedDocument, parse_authorized_document
from app.services.tax.txt_import import ParsedTxtRow, parse_received_txt

# Entradas de ZIP que no son evidencia: metadatos que agrega macOS al comprimir
# desde Finder. Ignorarlas evita procesar basura (y es el mismo motivo por el que
# un ZIP hecho asi es rechazado por el SRI: ver `ats.py`).
_IGNORED_ZIP_PREFIXES = ("__MACOSX/", ".")
_RELATED_SOURCE_TYPES = {"FACTURA", "LIQUIDACION", "NOTA_DEBITO"}


@dataclass
class IngestResult:
    """Resumen de una ingesta, para mostrarlo al usuario sin adivinanzas."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    preliminary: int = 0
    notes: list[str] = field(default_factory=list)


def normalize_sri_document_number(value: str | None) -> str | None:
    """Normaliza ``001001000000001`` o su variante con guiones.

    Un numero distinto de los 15 digitos del SRI queda sin resolver: enlazarlo
    por aproximacion podria aplicar una nota a una compra equivocada.
    """
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 15:
        return None
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


async def _resolve_related_access_key(
    session: AsyncSession,
    context: AuthContext,
    *,
    document: FiscalDocument,
) -> None:
    if document.doc_type != "NOTA_CREDITO" or not document.related_document_number:
        return
    normalized = normalize_sri_document_number(document.related_document_number)
    document.related_document_number = normalized
    if normalized is None or not document.counterparty_identification:
        document.related_access_key = None
        return
    if (
        not document.is_preliminary
        and document.related_document_type not in _RELATED_SOURCE_TYPES
    ):
        # El XML autorizado debe indicar codDocModificado. Solo el TXT, que es
        # preliminar y no trae ese código, puede usar la búsqueda amplia.
        document.related_access_key = None
        return
    establishment, emission_point, sequential = normalized.split("-")
    source_types: set[str] = (
        {document.related_document_type}
        if document.related_document_type in _RELATED_SOURCE_TYPES
        else _RELATED_SOURCE_TYPES
    )
    matches = list(
        await session.scalars(
            select(FiscalDocument)
            .where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.direction == document.direction,
                FiscalDocument.doc_type.in_(source_types),
                FiscalDocument.counterparty_identification
                == document.counterparty_identification,
                FiscalDocument.establishment_code == establishment,
                FiscalDocument.emission_point_code == emission_point,
                FiscalDocument.sequential == sequential,
            )
            .limit(2)
        )
    )
    document.related_access_key = matches[0].access_key if len(matches) == 1 else None


async def _sync_related_credit_notes(
    session: AsyncSession,
    context: AuthContext,
    *,
    source: FiscalDocument,
) -> None:
    if source.doc_type not in _RELATED_SOURCE_TYPES or not source.access_key:
        return
    number = normalize_sri_document_number(
        "-".join(
            part
            for part in (
                source.establishment_code,
                source.emission_point_code,
                source.sequential,
            )
            if part
        )
    )
    if number is None or not source.counterparty_identification:
        return
    notes = list(
        await session.scalars(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.direction == source.direction,
                FiscalDocument.doc_type == "NOTA_CREDITO",
                FiscalDocument.counterparty_identification
                == source.counterparty_identification,
                FiscalDocument.related_document_number == number,
            )
        )
    )
    if not notes:
        return
    from app.services import payables

    for note in notes:
        await _resolve_related_access_key(session, context, document=note)
        if note.related_access_key == source.access_key:
            await payables.sync_fiscal_document(session, context, document=note)


def _direction_for(document_identification: str, tenant_ruc: str) -> str:
    """EMITIDO si el emisor es la propia entidad; RECIBIDO en caso contrario."""
    return "EMITIDO" if document_identification == tenant_ruc else "RECIBIDO"


def extract_xml_members(data: bytes) -> list[tuple[str, bytes]]:
    """XML contenidos en un ZIP, ignorando metadatos de macOS y carpetas."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Invalid ZIP file") from exc

    members: list[tuple[str, bytes]] = []
    for name in archive.namelist():
        base = name.rsplit("/", 1)[-1]
        if name.endswith("/") or not base.lower().endswith(".xml"):
            continue
        if name.startswith(_IGNORED_ZIP_PREFIXES) or base.startswith("."):
            continue
        members.append((name, archive.read(name)))
    return members


async def upsert_parsed_document(
    session: AsyncSession,
    context: AuthContext,
    *,
    parsed: ParsedDocument,
    tenant_ruc: str,
    evidence_id: uuid.UUID | None,
    sales_document_id: uuid.UUID | None = None,
) -> tuple[FiscalDocument, bool]:
    """Crea o actualiza el comprobante y su detalle. Devuelve ``(doc, creado)``."""
    period = await periods_service.get_or_create_period(
        session,
        context,
        year=parsed.issue_date.year,
        month=parsed.issue_date.month,
        obligation_type="IVA",
    )

    existing = await session.scalar(
        select(FiscalDocument).where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.access_key == parsed.access_key,
        )
    )
    created = existing is None
    if existing is not None and not existing.is_preliminary and parsed.doc_type == "NOTA_CREDITO":
        parsed_number = normalize_sri_document_number(parsed.modified_document)
        relationship_changed = (
            existing.related_document_number is not None
            and existing.related_document_number != parsed_number
        ) or (
            existing.related_document_type is not None
            and existing.related_document_type != parsed.modified_document_type
        )
        if relationship_changed:
            raise HTTPException(
                status_code=409,
                detail="An authorized credit note cannot change its modified document",
            )
    document = existing or FiscalDocument(
        tenant_id=context.tenant_id,
        access_key=parsed.access_key,
    )

    counterparty_is_issuer = _direction_for(parsed.issuer_identification, tenant_ruc) == "RECIBIDO"
    document.tax_period_id = period.id
    document.direction = _direction_for(parsed.issuer_identification, tenant_ruc)
    document.doc_type = parsed.doc_type
    document.authorization_number = parsed.authorization_number
    document.authorized_at = parsed.authorized_at
    document.issue_date = parsed.issue_date
    document.establishment_code = parsed.establishment_code
    document.emission_point_code = parsed.emission_point_code
    document.sequential = parsed.sequential
    document.counterparty_identification = (
        parsed.issuer_identification if counterparty_is_issuer else parsed.receiver_identification
    )
    document.counterparty_name = (
        parsed.issuer_name if counterparty_is_issuer else parsed.receiver_name
    )
    document.subtotal = parsed.subtotal
    document.tax_total = parsed.tax_total
    document.total = parsed.total
    document.payment_methods = list(parsed.payment_methods)
    normalized_modified = normalize_sri_document_number(parsed.modified_document)
    if normalized_modified != document.related_document_number:
        document.related_access_key = None
    document.related_document_number = normalized_modified
    document.related_document_type = parsed.modified_document_type
    # El XML trae el detalle completo: deja de ser preliminar.
    document.is_preliminary = False
    if evidence_id is not None:
        document.evidence_id = evidence_id
    # Enlace al comprobante propio que origino este registro (ventas emitidas
    # por IAERP), para poder rastrear de donde salio sin duplicar la fuente.
    if sales_document_id is not None:
        document.sales_document_id = sales_document_id
    if parsed.retentions:
        document.related_access_key = document.related_access_key or None

    if created:
        session.add(document)
    await session.flush()

    # El detalle se reemplaza: el XML autorizado es la fuente de verdad.
    for table in (FiscalDocumentTax, FiscalRetention):
        for row in await session.scalars(
            select(table).where(
                table.tenant_id == context.tenant_id,
                table.fiscal_document_id == document.id,
            )
        ):
            await session.delete(row)

    for tax in parsed.taxes:
        session.add(
            FiscalDocumentTax(
                tenant_id=context.tenant_id,
                fiscal_document_id=document.id,
                sri_tax_code=tax.sri_tax_code,
                tax_bracket=tax.tax_bracket,
                rate=tax.rate,
                base_amount=tax.base_amount,
                tax_amount=tax.tax_amount,
            )
        )
    for retention in parsed.retentions:
        session.add(
            FiscalRetention(
                tenant_id=context.tenant_id,
                fiscal_document_id=document.id,
                kind=retention.kind,
                sri_code=retention.sri_code,
                percentage=retention.percentage,
                base_amount=retention.base_amount,
                retained_amount=retention.retained_amount,
                supporting_document_number=retention.supporting_document_number,
            )
        )

    await session.flush()
    from app.services import payables

    await _resolve_related_access_key(session, context, document=document)
    await payables.sync_fiscal_document(session, context, document=document)
    await _sync_related_credit_notes(session, context, source=document)
    return document, created


async def _upsert_txt_row(
    session: AsyncSession,
    context: AuthContext,
    *,
    row: ParsedTxtRow,
    tenant_ruc: str,
    evidence_id: uuid.UUID | None,
) -> tuple[bool, bool]:
    """Crea el comprobante desde una fila del TXT. Devuelve ``(creado, omitido)``.

    Si el comprobante ya existe con detalle del XML, la fila del TXT se omite:
    el XML es mas confiable y no debe degradarse a preliminar.
    """
    existing = await session.scalar(
        select(FiscalDocument).where(
            FiscalDocument.tenant_id == context.tenant_id,
            FiscalDocument.access_key == row.access_key,
        )
    )
    if existing is not None and not existing.is_preliminary:
        return False, True

    period = await periods_service.get_or_create_period(
        session,
        context,
        year=row.issue_date.year,
        month=row.issue_date.month,
        obligation_type="IVA",
    )

    created = existing is None
    document = existing or FiscalDocument(
        tenant_id=context.tenant_id,
        access_key=row.access_key,
    )
    counterparty_is_issuer = _direction_for(row.issuer_identification, tenant_ruc) == "RECIBIDO"
    document.tax_period_id = period.id
    document.direction = _direction_for(row.issuer_identification, tenant_ruc)
    document.doc_type = row.doc_type
    document.authorization_number = row.access_key
    document.issue_date = row.issue_date
    document.counterparty_identification = (
        row.issuer_identification if counterparty_is_issuer else row.receiver_identification
    )
    document.counterparty_name = row.issuer_name if counterparty_is_issuer else None
    document.subtotal = row.subtotal or document.subtotal
    document.tax_total = row.tax_total or document.tax_total
    document.total = row.total or document.total
    document.is_preliminary = row.is_preliminary
    normalized_modified = normalize_sri_document_number(row.modified_document)
    if normalized_modified != document.related_document_number:
        document.related_access_key = None
    document.related_document_number = normalized_modified
    document.related_document_type = None
    if evidence_id is not None:
        document.evidence_id = evidence_id

    if row.series:
        parts = row.series.split("-")
        if len(parts) == 3:
            document.establishment_code, document.emission_point_code, document.sequential = parts

    if created:
        session.add(document)
    await session.flush()
    from app.services import payables

    await _resolve_related_access_key(session, context, document=document)
    await payables.sync_fiscal_document(session, context, document=document)
    await _sync_related_credit_notes(session, context, source=document)
    return created, False


async def ingest_evidence(
    session: AsyncSession,
    context: AuthContext,
    *,
    evidence_id: uuid.UUID,
    tenant_ruc: str,
) -> IngestResult:
    """Lee un archivo ya cargado y persiste los comprobantes que contiene."""
    evidence = await session.scalar(
        select(TaxEvidence).where(
            TaxEvidence.tenant_id == context.tenant_id,
            TaxEvidence.id == evidence_id,
        )
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    result = IngestResult()
    if evidence.file_type == "PDF":
        # Regla del ADR 0012: los PDF no se leen. Quedan como respaldo.
        result.notes.append(
            "Los PDF se conservan como evidencia, pero sus valores no se leen "
            "automaticamente. Carga el XML autorizado para obtener el detalle."
        )
        return result

    data = await storage.download_artifact(object_key=evidence.object_key)

    payloads: list[bytes] = []
    if evidence.file_type == "ZIP":
        members = extract_xml_members(data)
        if not members:
            result.notes.append("El ZIP no contiene XML procesables.")
            return result
        payloads = [content for _name, content in members]
    elif evidence.file_type == "XML":
        payloads = [data]

    for payload in payloads:
        parsed = parse_authorized_document(payload)
        _document, created = await upsert_parsed_document(
            session,
            context,
            parsed=parsed,
            tenant_ruc=tenant_ruc,
            evidence_id=evidence.id,
        )
        if created:
            result.created += 1
        else:
            result.updated += 1

    if evidence.file_type == "TXT":
        for row in parse_received_txt(data):
            created, skipped = await _upsert_txt_row(
                session,
                context,
                row=row,
                tenant_ruc=tenant_ruc,
                evidence_id=evidence.id,
            )
            if skipped:
                result.skipped += 1
                continue
            if created:
                result.created += 1
            else:
                result.updated += 1
            if row.is_preliminary:
                result.preliminary += 1
                if row.preliminary_reason and row.preliminary_reason not in result.notes:
                    result.notes.append(row.preliminary_reason)

    await periods_service.refresh_period_statuses(session, context)

    return result


__all__ = [
    "IngestResult",
    "extract_xml_members",
    "ingest_evidence",
    "normalize_sri_document_number",
    "upsert_parsed_document",
]

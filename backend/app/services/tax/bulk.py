"""Carga en bloque de comprobantes del SRI (ADR 0012).

El usuario descarga del portal la carpeta completa de un mes (emitidos,
recibidos, retenciones) y la sube de una vez. Este modulo:

1. **Clasifica** cada archivo leyendo su contenido, no su nombre: tipo de
   comprobante, si es emitido o recibido (comparando el RUC del emisor con el de
   la entidad) y **a que periodo va segun la fecha real de emision**.
2. Muestra un **previo** que no escribe nada, para revisar antes de confirmar.
3. Al confirmar, guarda la evidencia (dedupe por hash) y crea o actualiza los
   ``FiscalDocument``.

Un archivo ilegible no aborta el lote: se reporta con su motivo y el resto se
procesa. Nada se adivina: lo que no se puede leer, no se registra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument
from app.services.tax import evidence as evidence_service
from app.services.tax import periods as periods_service
from app.services.tax.ingest import extract_xml_members, upsert_parsed_document
from app.services.tax.sri_xml import ParsedDocument, parse_authorized_document
from app.services.tax.txt_import import parse_received_txt

# Mismo limite que el lote de retenciones de cartera, por coherencia.
MAX_BULK_FILES = 50


@dataclass
class BulkItem:
    """Una entrada del lote ya clasificada (o rechazada, con su motivo)."""

    filename: str
    # Cuando un ZIP trae varios XML, cada uno aparece con su nombre interno.
    source_archive: str | None = None
    status: str = "OK"  # OK | DUPLICADO | ERROR
    doc_type: str | None = None
    direction: str | None = None
    access_key: str | None = None
    issue_date: str | None = None
    period_year: int | None = None
    period_month: int | None = None
    counterparty_identification: str | None = None
    counterparty_name: str | None = None
    total: Decimal | None = None
    # Solo para retenciones recibidas: si se puede aplicar a cartera.
    is_retention: bool = False
    error: str | None = None


@dataclass
class BulkResult:
    items: list[BulkItem] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    duplicates: int = 0
    errors: int = 0
    # Resumen por periodo: {"2025-11": 4, "2025-12": 2}
    periods: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def retention_count(self) -> int:
        return sum(1 for item in self.items if item.is_retention and item.status != "ERROR")


def _period_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _expand(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes, str | None]]:
    """Expande los ZIP a sus XML. Devuelve ``(nombre, contenido, zip_origen)``."""
    expanded: list[tuple[str, bytes, str | None]] = []
    for filename, content in files:
        if filename.lower().endswith(".zip"):
            try:
                members = extract_xml_members(content)
            except HTTPException:
                expanded.append((filename, content, None))
                continue
            if not members:
                expanded.append((filename, content, None))
                continue
            expanded.extend((name, data, filename) for name, data in members)
        else:
            expanded.append((filename, content, None))
    return expanded


def _item_from_parsed(
    parsed: ParsedDocument,
    *,
    filename: str,
    source_archive: str | None,
    tenant_ruc: str,
) -> BulkItem:
    direction = "EMITIDO" if parsed.issuer_identification == tenant_ruc else "RECIBIDO"
    counterparty_is_issuer = direction == "RECIBIDO"
    return BulkItem(
        filename=filename,
        source_archive=source_archive,
        doc_type=parsed.doc_type,
        direction=direction,
        access_key=parsed.access_key,
        issue_date=parsed.issue_date.isoformat(),
        period_year=parsed.issue_date.year,
        period_month=parsed.issue_date.month,
        counterparty_identification=(
            parsed.issuer_identification
            if counterparty_is_issuer
            else parsed.receiver_identification
        ),
        counterparty_name=(
            parsed.issuer_name if counterparty_is_issuer else parsed.receiver_name
        ),
        total=parsed.total,
        # Una retencion RECIBIDA es la que le hicieron a la entidad: es la que
        # puede aplicarse a la cartera de su factura.
        is_retention=parsed.doc_type == "RETENCION" and direction == "RECIBIDO",
    )


async def preview_bulk(
    session: AsyncSession,
    context: AuthContext,
    *,
    files: list[tuple[str, bytes]],
    tenant_ruc: str,
) -> BulkResult:
    """Clasifica el lote SIN escribir nada."""
    result = BulkResult()

    for filename, content, archive in _expand(files):
        lowered = filename.lower()

        if lowered.endswith(".txt") or lowered.endswith(".csv"):
            try:
                rows = parse_received_txt(content)
            except HTTPException as exc:
                result.items.append(
                    BulkItem(
                        filename=filename,
                        source_archive=archive,
                        status="ERROR",
                        error=str(exc.detail),
                    )
                )
                result.errors += 1
                continue
            for row in rows:
                result.items.append(
                    BulkItem(
                        filename=filename,
                        source_archive=archive,
                        doc_type=row.doc_type,
                        direction="RECIBIDO",
                        access_key=row.access_key,
                        issue_date=row.issue_date.isoformat(),
                        period_year=row.issue_date.year,
                        period_month=row.issue_date.month,
                        counterparty_identification=row.issuer_identification,
                        counterparty_name=row.issuer_name,
                        total=row.total,
                    )
                )
                key = _period_key(row.issue_date.year, row.issue_date.month)
                result.periods[key] = result.periods.get(key, 0) + 1
            continue

        if lowered.endswith(".pdf"):
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="ERROR",
                    error=(
                        "Los PDF se guardan como respaldo, pero sus valores no se leen. "
                        "Carga el XML autorizado."
                    ),
                )
            )
            result.errors += 1
            continue

        try:
            parsed = parse_authorized_document(content)
        except HTTPException as exc:
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="ERROR",
                    error=str(exc.detail),
                )
            )
            result.errors += 1
            continue

        item = _item_from_parsed(
            parsed,
            filename=filename,
            source_archive=archive,
            tenant_ruc=tenant_ruc,
        )

        existing = await session.scalar(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.access_key == parsed.access_key,
            )
        )
        if existing is not None and not existing.is_preliminary:
            item.status = "DUPLICADO"
            result.duplicates += 1

        result.items.append(item)
        assert item.period_year is not None and item.period_month is not None
        key = _period_key(item.period_year, item.period_month)
        result.periods[key] = result.periods.get(key, 0) + 1

    if result.errors:
        result.notes.append(
            f"{result.errors} archivo(s) no se pudieron leer; el resto si se procesara."
        )
    return result


async def apply_bulk(
    session: AsyncSession,
    context: AuthContext,
    *,
    files: list[tuple[str, bytes]],
    tenant_ruc: str,
) -> BulkResult:
    """Guarda la evidencia y registra los comprobantes del lote."""
    result = BulkResult()

    for filename, content, archive in _expand(files):
        lowered = filename.lower()

        # La evidencia se guarda siempre: el archivo original es el respaldo,
        # aunque su contenido no se pueda interpretar.
        try:
            evidence, duplicate_file = await evidence_service.upload_evidence(
                session,
                context,
                filename=filename,
                data=content,
                origin="PORTAL_SRI",
            )
        except HTTPException as exc:
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="ERROR",
                    error=str(exc.detail),
                )
            )
            result.errors += 1
            continue

        if lowered.endswith(".pdf"):
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="OK",
                    doc_type="PDF",
                    error=(
                        "Guardado como respaldo; sus valores no se leen automaticamente."
                    ),
                )
            )
            continue

        if lowered.endswith(".txt") or lowered.endswith(".csv"):
            # El TXT se procesa con la ingesta existente, que ya marca
            # preliminares las filas sin valores.
            from app.services.tax.ingest import ingest_evidence

            ingest = await ingest_evidence(
                session,
                context,
                evidence_id=evidence.id,
                tenant_ruc=tenant_ruc,
            )
            result.created += ingest.created
            result.updated += ingest.updated
            for note in ingest.notes:
                if note not in result.notes:
                    result.notes.append(note)
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="OK",
                    doc_type="LISTADO",
                )
            )
            continue

        try:
            parsed = parse_authorized_document(content)
        except HTTPException as exc:
            result.items.append(
                BulkItem(
                    filename=filename,
                    source_archive=archive,
                    status="ERROR",
                    error=str(exc.detail),
                )
            )
            result.errors += 1
            continue

        item = _item_from_parsed(
            parsed,
            filename=filename,
            source_archive=archive,
            tenant_ruc=tenant_ruc,
        )
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
            if duplicate_file:
                item.status = "DUPLICADO"
                result.duplicates += 1

        result.items.append(item)
        assert item.period_year is not None and item.period_month is not None
        key = _period_key(item.period_year, item.period_month)
        result.periods[key] = result.periods.get(key, 0) + 1

    # Los estados de periodo se recalculan una sola vez al final del lote.
    await periods_service.refresh_period_statuses(session, context)

    if result.errors:
        result.notes.append(
            f"{result.errors} archivo(s) no se pudieron leer y no se registraron."
        )
    return result


def retention_files(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Archivos del lote que son comprobantes de retencion, para cartera.

    Se usan tal cual para delegar en ``receivables.import_retention_xml_batch``,
    que ya sabe cruzarlos con la factura y registrar el movimiento.
    """
    selected: list[tuple[str, bytes]] = []
    for filename, content, _archive in _expand(files):
        if filename.lower().endswith(".xml"):
            try:
                parsed = parse_authorized_document(content)
            except HTTPException:
                continue
            if parsed.doc_type == "RETENCION":
                selected.append((filename, content))
    return selected


__all__ = [
    "MAX_BULK_FILES",
    "BulkItem",
    "BulkResult",
    "apply_bulk",
    "preview_bulk",
    "retention_files",
]

"""Caso de uso diario: importar reportes recibidos y pedir sus XML al SRI."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import TaxEvidence, TaxXmlRecoveryJob
from app.services import storage
from app.services.tax import ingest, periods, xml_recovery
from app.services.tax.txt_import import parse_received_txt

MAX_MONTHLY_REPORTS = 5


@dataclass(frozen=True)
class ReceivedReportsResult:
    report_year: int
    report_month: int
    evidence_count: int
    listed_rows: int
    document_types: dict[str, int]
    created: int
    updated: int
    skipped: int
    preliminary: int
    recovery_job: TaxXmlRecoveryJob


async def process_received_reports(
    session: AsyncSession,
    context: AuthContext,
    *,
    evidence_ids: list[uuid.UUID],
    report_year: int,
    report_month: int,
    tenant_ruc: str,
) -> ReceivedReportsResult:
    """Valida e importa los TXT de un mes y crea un trabajo de recuperacion.

    El flujo local consulta los cinco tipos del portal para el mes completo. Los
    archivos se aceptan solo si todas sus filas pertenecen al periodo pedido;
    asi un resultado viejo que el portal dejo en pantalla no mezcla meses.
    """
    unique_ids = list(dict.fromkeys(evidence_ids))
    if len(unique_ids) != len(evidence_ids):
        raise HTTPException(status_code=422, detail="Evidence IDs must be unique")
    if not 1 <= len(unique_ids) <= MAX_MONTHLY_REPORTS:
        raise HTTPException(
            status_code=422,
            detail=f"Between 1 and {MAX_MONTHLY_REPORTS} evidence files are required",
        )

    evidence_by_id = {
        evidence.id: evidence
        for evidence in await session.scalars(
            select(TaxEvidence).where(
                TaxEvidence.tenant_id == context.tenant_id,
                TaxEvidence.id.in_(unique_ids),
            )
        )
    }
    if len(evidence_by_id) != len(unique_ids):
        raise HTTPException(status_code=404, detail="Evidence not found")

    listed_rows = 0
    document_types: Counter[str] = Counter()
    for evidence_id in unique_ids:
        evidence = evidence_by_id[evidence_id]
        if evidence.file_type != "TXT":
            raise HTTPException(
                status_code=422,
                detail="Daily received reports must be TXT files",
            )
        rows = parse_received_txt(await storage.download_artifact(object_key=evidence.object_key))
        if not rows:
            raise HTTPException(status_code=422, detail="SRI report contains no rows")
        if any(
            row.issue_date.year != report_year or row.issue_date.month != report_month
            for row in rows
        ):
            raise HTTPException(
                status_code=422,
                detail="Every report row must match reportYear and reportMonth",
            )
        listed_rows += len(rows)
        document_types.update(row.doc_type for row in rows)

    created = updated = skipped = preliminary = 0
    for evidence_id in unique_ids:
        result = await ingest.ingest_evidence(
            session,
            context,
            evidence_id=evidence_id,
            tenant_ruc=tenant_ruc,
        )
        created += result.created
        updated += result.updated
        skipped += result.skipped
        preliminary += result.preliminary

    period = await periods.get_or_create_period(
        session,
        context,
        year=report_year,
        month=report_month,
        obligation_type="IVA",
    )
    recovery_job = await xml_recovery.create_job(session, context, period_id=period.id)
    return ReceivedReportsResult(
        report_year=report_year,
        report_month=report_month,
        evidence_count=len(unique_ids),
        listed_rows=listed_rows,
        document_types=dict(sorted(document_types.items())),
        created=created,
        updated=updated,
        skipped=skipped,
        preliminary=preliminary,
        recovery_job=recovery_job,
    )


__all__ = [
    "MAX_MONTHLY_REPORTS",
    "ReceivedReportsResult",
    "process_received_reports",
]

"""Recupera XML recibidos sin mantener una transacción durante la llamada SRI."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.db.session import SessionFactory
from app.integrations.sri.protocol import SRIClient
from app.integrations.sri.soap import SoapSRIClient
from app.models.platform import OutboxEvent, Tenant
from app.models.tax import FiscalDocument, TaxPeriod, TaxXmlRecoveryItem, TaxXmlRecoveryJob
from app.services.tax import evidence, ingest, periods
from app.services.tax.sri_xml import parse_authorized_document
from app.services.unit_of_work import append_audit
from app.workers.outbox import OutboxMessage

settings = get_settings()
CONSUMER_NAME = "iaerp.tax_xml_recovery"
LEASE_DURATION = timedelta(minutes=3)
REQUEST_DELAY_SECONDS = 0.25


class RecoveryAlreadyRunningError(RuntimeError):
    pass


class RecoveryEvidenceRejectedError(ValueError):
    """El SRI respondió, pero la evidencia no corresponde al ítem solicitado."""


def _reject_unless(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryEvidenceRejectedError(message)


def _default_client() -> SRIClient:
    return SoapSRIClient(
        environment=settings.SRI_ENVIRONMENT,
        authorization_url=settings.SRI_AUTHORIZATION_URL,
        timeout=settings.SRI_HTTP_TIMEOUT,
    )


def _context(job: TaxXmlRecoveryJob) -> AuthContext:
    return AuthContext(
        actor_id=job.requested_by_actor_id,
        actor_type=job.requested_by_actor_type,
        tenant_id=job.tenant_id,
        roles=frozenset(),
        scopes=frozenset({"tax:write"}),
        token_id=f"tax-xml-recovery:{job.id}",
    )


def _apply_item_status(
    job: TaxXmlRecoveryJob,
    *,
    item: TaxXmlRecoveryItem,
    status: str,
) -> None:
    if item.status != "PENDING":
        return
    item.status = status
    job.processed_count += 1
    if status == "RECOVERED":
        job.recovered_count += 1
    elif status == "UNAVAILABLE":
        job.unavailable_count += 1
    elif status == "FAILED":
        job.failed_count += 1
    job.lease_until = datetime.now(UTC) + LEASE_DURATION


async def _mark_item(
    job_id: uuid.UUID,
    *,
    document_id: str,
    status: str,
) -> None:
    async with SessionFactory() as session, session.begin():
        job = await session.get(TaxXmlRecoveryJob, job_id, with_for_update=True)
        if job is None:
            return
        item = await session.scalar(
            select(TaxXmlRecoveryItem)
            .where(
                TaxXmlRecoveryItem.tenant_id == job.tenant_id,
                TaxXmlRecoveryItem.job_id == job_id,
                TaxXmlRecoveryItem.fiscal_document_id == uuid.UUID(document_id),
            )
            .with_for_update()
        )
        if item is not None:
            _apply_item_status(job, item=item, status=status)


async def _complete(job_id: uuid.UUID) -> None:
    async with SessionFactory() as session, session.begin():
        job = await session.get(TaxXmlRecoveryJob, job_id, with_for_update=True)
        if job is None:
            return
        job.status = "COMPLETED"
        job.lease_until = None
        job.completed_at = datetime.now(UTC)


async def run_recovery_job(
    job_id: uuid.UUID,
    *,
    sri_client: SRIClient | None = None,
) -> None:
    client = sri_client or _default_client()
    async with SessionFactory() as session, session.begin():
        job = await session.get(TaxXmlRecoveryJob, job_id, with_for_update=True)
        if job is None or job.status == "COMPLETED":
            return
        now = datetime.now(UTC)
        lease_until = job.lease_until
        if lease_until is not None and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=UTC)
        if job.status == "RUNNING" and lease_until is not None and lease_until > now:
            raise RecoveryAlreadyRunningError("XML recovery job has an active lease")
        job.status = "RUNNING"
        job.lease_until = now + LEASE_DURATION
        job.started_at = job.started_at or now
        item_ids = list(
            await session.scalars(
                select(TaxXmlRecoveryItem.fiscal_document_id)
                .where(
                    TaxXmlRecoveryItem.tenant_id == job.tenant_id,
                    TaxXmlRecoveryItem.job_id == job.id,
                    TaxXmlRecoveryItem.status == "PENDING",
                )
                .order_by(TaxXmlRecoveryItem.created_at, TaxXmlRecoveryItem.id)
            )
        )
        tenant_id = job.tenant_id
        period_id = job.tax_period_id

    for item_index, document_id in enumerate(item_ids):
        if item_index > 0:
            # Consulta secuencial y pausada: evita ráfagas contra el servicio SRI.
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        async with SessionFactory() as session:
            document = await session.scalar(
                select(FiscalDocument).where(
                    FiscalDocument.tenant_id == tenant_id,
                    FiscalDocument.id == document_id,
                    FiscalDocument.tax_period_id == period_id,
                )
            )
            access_key = document.access_key if document is not None else None
            already_complete = document is not None and not document.is_preliminary
        if document is None or access_key is None:
            await _mark_item(job_id, document_id=str(document_id), status="FAILED")
            continue
        if already_complete:
            await _mark_item(job_id, document_id=str(document_id), status="RECOVERED")
            continue

        result = None
        for attempt in range(3):
            try:
                # No hay sesión ni transacción abierta durante esta llamada externa.
                result = await client.check_authorization(access_key)
                break
            except Exception:  # noqa: BLE001 - se reintenta sin registrar clave/XML
                if attempt == 2:
                    # Es un fallo técnico, no un rechazo del comprobante. Se
                    # propaga para que Celery reintente y el ítem siga PENDING.
                    raise
                else:
                    await asyncio.sleep(2**attempt)
        assert result is not None
        if result.status != "AUTHORIZED" or result.authorized_xml is None:
            await _mark_item(job_id, document_id=str(document_id), status="UNAVAILABLE")
            continue

        try:
            parsed = parse_authorized_document(result.authorized_xml)
        except HTTPException:
            await _mark_item(job_id, document_id=str(document_id), status="FAILED")
            continue

        try:
            _reject_unless(
                parsed.access_key == access_key,
                "SRI response access key does not match request",
            )

            async with SessionFactory() as session, session.begin():
                await session.scalar(
                    select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
                )
                job = await session.get(TaxXmlRecoveryJob, job_id, with_for_update=True)
                item = await session.scalar(
                    select(TaxXmlRecoveryItem)
                    .where(
                        TaxXmlRecoveryItem.tenant_id == tenant_id,
                        TaxXmlRecoveryItem.job_id == job_id,
                        TaxXmlRecoveryItem.fiscal_document_id == document_id,
                    )
                    .with_for_update()
                )
                tenant = await session.get(Tenant, tenant_id)
                period = await session.scalar(
                    select(TaxPeriod).where(
                        TaxPeriod.tenant_id == tenant_id,
                        TaxPeriod.id == period_id,
                    )
                )
                current = await session.scalar(
                    select(FiscalDocument).where(
                        FiscalDocument.tenant_id == tenant_id,
                        FiscalDocument.id == document_id,
                    )
                )
                _reject_unless(
                    job is not None
                    and item is not None
                    and tenant is not None
                    and period is not None
                    and current is not None,
                    "Recovery context no longer exists",
                )
                assert job is not None
                assert item is not None
                assert tenant is not None
                assert period is not None
                assert current is not None
                _reject_unless(
                    parsed.receiver_identification == tenant.ruc,
                    "SRI response receiver does not match tenant",
                )
                _reject_unless(
                    parsed.authorization_number == access_key,
                    "SRI authorization number does not match access key",
                )
                _reject_unless(
                    parsed.issuer_identification == access_key[10:23],
                    "SRI issuer does not match access key",
                )
                _reject_unless(
                    current.doc_type == parsed.doc_type,
                    "SRI response document type does not match queued document",
                )
                _reject_unless(
                    not current.counterparty_identification
                    or current.counterparty_identification == parsed.issuer_identification,
                    "SRI response issuer does not match queued document",
                )
                _reject_unless(
                    (parsed.issue_date.year, parsed.issue_date.month)
                    == (period.year, period.month),
                    "SRI response belongs to a different tax period",
                )
                context = _context(job)
                record, _duplicate = await evidence.upload_evidence(
                    session,
                    context,
                    filename=f"sri-recovered-{document_id}.xml",
                    data=result.authorized_xml,
                    origin="SRI_AUTHORIZATION_WS",
                    tax_period_id=job.tax_period_id,
                )
                recovered, _created = await ingest.upsert_parsed_document(
                    session,
                    context,
                    parsed=parsed,
                    tenant_ruc=tenant.ruc,
                    evidence_id=record.id,
                )
                _reject_unless(
                    recovered.id == current.id and recovered.tax_period_id == job.tax_period_id,
                    "Recovered XML does not match queued fiscal document",
                )
                await periods.refresh_period_statuses(
                    session,
                    context,
                    period_id=job.tax_period_id,
                )
                await append_audit(
                    session,
                    context=context,
                    action="tax.evidence.sri_recovered",
                    entity_type="fiscal_document",
                    entity_id=str(recovered.id),
                    correlation_id=str(job.id),
                    idempotency_key=f"{job.id}:{recovered.id}",
                    details={"source": "SRI_AUTHORIZATION_WS"},
                )
                session.add(
                    OutboxEvent(
                        tenant_id=tenant_id,
                        event_type="tax.evidence.sri_recovered",
                        aggregate_type="fiscal_document",
                        aggregate_id=str(recovered.id),
                        payload={"entity_id": str(recovered.id), "job_id": str(job.id)},
                        correlation_id=str(job.id),
                        available_at=datetime.now(UTC),
                    )
                )
                # El avance del trabajo comparte el commit con evidencia,
                # ingesta, auditoría y outbox: un crash no duplica el cierre.
                _apply_item_status(
                    job,
                    item=item,
                    status="RECOVERED",
                )
        except RecoveryEvidenceRejectedError:
            await _mark_item(job_id, document_id=str(document_id), status="FAILED")

    await _complete(job_id)


async def handle_recovery_requested(message: OutboxMessage) -> None:
    job_id = uuid.UUID(message.aggregate_id)
    try:
        await run_recovery_job(job_id)
    except RecoveryAlreadyRunningError:
        raise
    except BaseException:
        # Un fallo técnico reabre el trabajo para que el autoretry de Celery
        # continúe desde los ítems que aún estén PENDING.
        async with SessionFactory() as session, session.begin():
            job = await session.get(TaxXmlRecoveryJob, job_id, with_for_update=True)
            if job is not None and job.status != "COMPLETED":
                job.status = "QUEUED"
                job.lease_until = None
        raise


__all__ = [
    "CONSUMER_NAME",
    "RecoveryAlreadyRunningError",
    "handle_recovery_requested",
    "run_recovery_job",
]

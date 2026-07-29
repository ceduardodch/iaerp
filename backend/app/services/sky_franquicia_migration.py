"""Read-only validation for historical invoices from Sky Franquicia.

The first migration gate intentionally does not persist source records.  It
produces an aggregate report and rejects data that cannot be represented
faithfully in IAERP.  In particular, it never calls SRI and never emits a
document in the destination.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.auth import AuthContext
from app.models.billing import (
    DocumentArtifact,
    SalesDocument,
    SalesDocumentInstallment,
    SalesDocumentLine,
    Sequence,
    SRITransmission,
)
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.platform import IdempotencyRecord, Tenant
from app.models.receivables import Receivable, ReceivableInstallment
from app.services import storage
from app.services.fiscal_policy import LineInput, resolve_fiscal_policy
from app.services.unit_of_work import append_audit, canonical_hash

_SUPPORTED_SOURCE_STATUSES = frozenset({"AUTHORIZED", "CANCELLED"})
_MONEY_QUANTUM = Decimal("0.01")
_MIGRATION_ACTOR_ID = "system:sky-franquicia-authorized-migration"
_MIGRATION_OPERATION = "sky_franquicia.authorized_invoice_import"


@dataclass(frozen=True)
class MigrationIssue:
    code: str
    source_reference: str
    message: str


def _source_reference(source_id: str) -> str:
    """Stable opaque reference: reports must not expose invoice/customer data."""

    return hashlib.sha256(source_id.encode()).hexdigest()[:12]


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_MONEY_QUANTUM)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid monetary value: {value!r}") from error


def validate_source_invoices(rows: list[dict[str, Any]]) -> list[MigrationIssue]:
    """Validate the fiscal minimum needed before a historical load.

    The source stores amounts as floating point.  Values are converted through
    strings and compared at cent precision, which is the target accounting
    precision.  A caller must stop before loading when this function returns
    any issue.
    """

    issues: list[MigrationIssue] = []
    access_keys: Counter[str] = Counter()
    for row in rows:
        reference = _source_reference(str(row["id"]))
        access_key = (row.get("sri_access_key") or "").strip()
        if len(access_key) != 49 or not access_key.isdigit():
            issues.append(
                MigrationIssue(
                    code="INVALID_ACCESS_KEY",
                    source_reference=reference,
                    message="The source access key must contain exactly 49 digits.",
                )
            )
        else:
            access_keys[access_key] += 1

        status = (row.get("status") or "").strip().upper()
        if status not in _SUPPORTED_SOURCE_STATUSES:
            issues.append(
                MigrationIssue(
                    code="UNSUPPORTED_STATUS",
                    source_reference=reference,
                    message=f"Historical status {status or 'NULL'} is not loadable.",
                )
            )
        if status == "AUTHORIZED" and (
            not row.get("sri_auth_code") or not row.get("sri_xml")
        ):
            issues.append(
                MigrationIssue(
                    code="AUTHORIZED_ARTIFACT_GAP",
                    source_reference=reference,
                    message="An authorized invoice is missing its authorization or XML.",
                )
            )

        line_count = int(row.get("line_count") or 0)
        if line_count == 0:
            issues.append(
                MigrationIssue(
                    code="MISSING_LINES",
                    source_reference=reference,
                    message="The source invoice has no lines.",
                )
            )
        try:
            # Sky stores ``subtotal_15`` and ``subtotal_0`` after discount.
            # ``discount`` is a separate informational total and must not be
            # subtracted again during reconciliation.
            source_subtotal = _decimal(row.get("subtotal_15")) + _decimal(
                row.get("subtotal_0")
            )
            line_subtotal = _decimal(row.get("line_subtotal"))
        except ValueError as error:
            issues.append(
                MigrationIssue(
                    code="INVALID_AMOUNT",
                    source_reference=reference,
                    message=str(error),
                )
            )
        else:
            if source_subtotal != line_subtotal:
                issues.append(
                    MigrationIssue(
                        code="LINE_SUBTOTAL_MISMATCH",
                        source_reference=reference,
                        message="Invoice lines do not reconcile with the source subtotal.",
                    )
                )

    for access_key, count in access_keys.items():
        if count > 1:
            issues.append(
                MigrationIssue(
                    code="DUPLICATE_ACCESS_KEY",
                    source_reference=hashlib.sha256(access_key.encode()).hexdigest()[:12],
                    message="More than one source invoice shares an SRI access key.",
                )
            )
    return issues


async def extract_source_invoices(
    *, source_url: str, ruc: str
) -> list[dict[str, Any]]:
    """Extract only invoice fields required for validation from a read-only snapshot."""

    source_engine: AsyncEngine = create_async_engine(source_url, pool_pre_ping=True)
    try:
        async with source_engine.connect() as connection:
            await connection.execute(text("BEGIN READ ONLY"))
            result = await connection.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.status,
                      i.establishment,
                      i.emission_point,
                      i.sequential,
                      i.issue_date,
                      i.subtotal_15,
                      i.subtotal_0,
                      i.discount,
                      i.tax,
                      i.total,
                      i.sri_access_key,
                      i.sri_auth_code,
                      i.sri_xml,
                      count(ii.id) AS line_count,
                      coalesce(sum(ii.total), 0) AS line_subtotal
                    FROM invoices i
                    JOIN franchises f ON f.id = i.franchise_id
                    JOIN profiles p ON p.id = f.profile_id
                    LEFT JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE p.ruc = :ruc
                    GROUP BY i.id
                    ORDER BY i.issue_date, i.establishment, i.emission_point, i.sequential
                    """
                ),
                {"ruc": ruc},
            )
            rows = [dict(row) for row in result.mappings().all()]
            await connection.execute(text("ROLLBACK"))
            return rows
    finally:
        await source_engine.dispose()


async def extract_authorized_source_invoices(
    *, source_url: str, ruc: str
) -> list[dict[str, Any]]:
    """Read complete authorized invoices and their source lines from Sky.

    The extraction is intentionally source-read-only.  It returns only the
    fields required to faithfully create a historical sales document, its
    customer, and its signed XML artifact in the destination.
    """

    source_engine: AsyncEngine = create_async_engine(source_url, pool_pre_ping=True)
    try:
        async with source_engine.connect() as connection:
            await connection.execute(text("BEGIN READ ONLY"))
            result = await connection.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.status,
                      i.establishment,
                      i.emission_point,
                      i.sequential,
                      i.issue_date,
                      i.subtotal_15,
                      i.subtotal_0,
                      i.discount,
                      i.tax,
                      i.total,
                      i.sri_access_key,
                      i.sri_auth_code,
                      i.sri_authorization_date,
                      i.sri_xml,
                      c.name AS customer_name,
                      c.document_type AS customer_document_type,
                      c.document_number AS customer_document_number,
                      c.email AS customer_email,
                      c.phone AS customer_phone,
                      c.address AS customer_address,
                      f.name AS franchise_name,
                      f.location AS franchise_location,
                      count(ii.id) AS line_count,
                      coalesce(sum(ii.total), 0) AS line_subtotal,
                      coalesce(
                        json_agg(
                          json_build_object(
                            'description', ii.description,
                            'quantity', ii.quantity,
                            'unit_price', ii.unit_price,
                            'discount', ii.discount,
                            'total', ii.total,
                            'is_taxable', ii.is_taxable
                          ) ORDER BY ii.id
                        ) FILTER (WHERE ii.id IS NOT NULL),
                        '[]'::json
                      ) AS lines
                    FROM invoices i
                    JOIN franchises f ON f.id = i.franchise_id
                    JOIN profiles p ON p.id = f.profile_id
                    LEFT JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN invoice_items ii ON ii.invoice_id = i.id
                    WHERE p.ruc = :ruc AND i.status = 'AUTHORIZED'
                    GROUP BY i.id, c.id, f.id
                    ORDER BY i.issue_date, i.establishment, i.emission_point, i.sequential
                    """
                ),
                {"ruc": ruc},
            )
            rows = [dict(row) for row in result.mappings().all()]
            await connection.execute(text("ROLLBACK"))
            return rows
    finally:
        await source_engine.dispose()


def _source_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _source_authorized_at(value: Any, *, fallback: date) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime(fallback.year, fallback.month, fallback.day, tzinfo=UTC)


def _identification(row: dict[str, Any]) -> tuple[str, str]:
    """Map Sky/SRI buyer identification into IAERP's constrained master."""

    raw_type = str(row.get("customer_document_type") or "").strip().lower()
    raw_number = str(row.get("customer_document_number") or "").strip()
    mapped = {
        "04": "RUC",
        "ruc": "RUC",
        "05": "CEDULA",
        "cedula": "CEDULA",
        "cédula": "CEDULA",
        "06": "PASSPORT",
        "pasaporte": "PASSPORT",
        "07": "FINAL_CONSUMER",
        "consumidor final": "FINAL_CONSUMER",
    }.get(raw_type)
    if mapped is None:
        if len(raw_number) == 13:
            mapped = "RUC"
        elif len(raw_number) == 10:
            mapped = "CEDULA"
        else:
            mapped = "FINAL_CONSUMER"
    if mapped == "FINAL_CONSUMER":
        return mapped, raw_number or "9999999999999"
    if not raw_number:
        raise ValueError("A non-final-consumer invoice needs a customer identification number.")
    return mapped, raw_number


def _tax_for_line(line: dict[str, Any]) -> tuple[str, Decimal]:
    # The authorized BTOB source range is in 2026.  Sky persists only the
    # taxable flag per line, so 15% is the only legal taxable rate for this
    # migration; the header/line reconciliation below verifies the result.
    return ("4", Decimal("15.000000")) if line.get("is_taxable") else ("0", Decimal("0.000000"))


def _migration_context(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        actor_id=_MIGRATION_ACTOR_ID,
        actor_type="SYSTEM",
        tenant_id=tenant_id,
        roles=frozenset({"owner"}),
        scopes=frozenset(),
        token_id="sky-franquicia-authorized-migration",
    )


async def _party_for_source_row(
    session: AsyncSession, *, tenant_id: uuid.UUID, row: dict[str, Any]
) -> Party:
    identification_type, identification_number = _identification(row)
    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == tenant_id,
            Party.identification_type == identification_type,
            Party.identification_number == identification_number,
        )
    )
    if party is not None:
        return party
    party_name = str(row.get("customer_name") or "CONSUMIDOR FINAL").strip()
    party = Party(
        tenant_id=tenant_id,
        name=(party_name or "CONSUMIDOR FINAL")[:200],
        identification_type=identification_type,
        identification_number=identification_number,
        roles=["CUSTOMER"],
        email=(str(row["customer_email"]).strip()[:320] if row.get("customer_email") else None),
        phone=(str(row["customer_phone"]).strip()[:40] if row.get("customer_phone") else None),
        address=(
            str(row["customer_address"]).strip()[:500]
            if row.get("customer_address")
            else None
        ),
        payment_terms_days=0,
        active=True,
    )
    session.add(party)
    await session.flush()
    return party


async def _fiscal_location_for_source_row(
    session: AsyncSession, *, tenant_id: uuid.UUID, row: dict[str, Any]
) -> tuple[Establishment, EmissionPoint]:
    establishment_code = str(row.get("establishment") or "001").zfill(3)[-3:]
    point_code = str(row.get("emission_point") or "001").zfill(3)[-3:]
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.tenant_id == tenant_id, Establishment.code == establishment_code
        )
    )
    if establishment is None:
        establishment_name = str(
            row.get("franchise_name") or f"Establecimiento {establishment_code}"
        ).strip()
        establishment_address = str(
            row.get("franchise_location") or "Direccion historica migrada"
        ).strip()
        establishment = Establishment(
            tenant_id=tenant_id,
            code=establishment_code,
            name=establishment_name[:120],
            address=establishment_address[:500],
            active=True,
        )
        session.add(establishment)
        await session.flush()
    point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.tenant_id == tenant_id,
            EmissionPoint.establishment_id == establishment.id,
            EmissionPoint.code == point_code,
        )
    )
    if point is None:
        point = EmissionPoint(
            tenant_id=tenant_id,
            establishment_id=establishment.id,
            code=point_code,
            active=True,
        )
        session.add(point)
        await session.flush()
    return establishment, point


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


async def _load_authorized_row(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    row: dict[str, Any],
    correlation_id: str,
) -> str:
    """Persist one validated historical invoice and its opening receivable."""

    issue_date = _source_date(row["issue_date"])
    lines = list(row["lines"])
    policy = resolve_fiscal_policy(issue_date)
    line_inputs: list[LineInput] = []
    line_tax: list[tuple[str, Decimal]] = []
    for source_line in lines:
        tax_code, tax_rate = _tax_for_line(source_line)
        line_tax.append((tax_code, tax_rate))
        line_inputs.append(
            LineInput(
                quantity=Decimal(str(source_line["quantity"])),
                unit_price=Decimal(str(source_line["unit_price"])),
                discount=_decimal(source_line.get("discount")),
                tax_rate=tax_rate,
                tax_sri_code=tax_code,
            )
        )
    calculation = policy.calculate_document(line_inputs)
    if (
        calculation.subtotal != _decimal(row["subtotal_15"]) + _decimal(row["subtotal_0"])
        or calculation.tax_total != _decimal(row["tax"])
        or calculation.total != _decimal(row["total"])
    ):
        raise ValueError(
            "Calculated historical totals do not reconcile with the authorized source invoice."
        )

    party = await _party_for_source_row(session, tenant_id=tenant_id, row=row)
    establishment, emission_point = await _fiscal_location_for_source_row(
        session, tenant_id=tenant_id, row=row
    )
    document = SalesDocument(
        tenant_id=tenant_id,
        document_type="INVOICE",
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=str(row["sequential"]).zfill(9),
        access_key=str(row["sri_access_key"]),
        party_id=party.id,
        issue_date=issue_date,
        status="AUTHORIZED",
        currency="USD",
        subtotal=calculation.subtotal,
        tax_total=calculation.tax_total,
        total=calculation.total,
        fiscal_policy_version=policy.version,
        authorization_number=str(row["sri_auth_code"]),
        authorized_at=_source_authorized_at(row.get("sri_authorization_date"), fallback=issue_date),
    )
    session.add(document)
    await session.flush()
    for line_number, (source_line, calculated, (tax_code, tax_rate)) in enumerate(
        zip(lines, calculation.lines, line_tax, strict=True), start=1
    ):
        session.add(
            SalesDocumentLine(
                tenant_id=tenant_id,
                sales_document_id=document.id,
                line_number=line_number,
                product_id=None,
                description=str(source_line["description"]).strip()[:500],
                quantity=calculated.quantity,
                unit_price=calculated.unit_price,
                discount=calculated.discount,
                base_amount=calculated.base_amount,
                tax_sri_code=tax_code,
                tax_rate=tax_rate,
                tax_amount=calculated.tax_amount,
            )
        )
    session.add(
        SalesDocumentInstallment(
            tenant_id=tenant_id,
            sales_document_id=document.id,
            sequence=1,
            due_date=issue_date,
            amount=document.total,
        )
    )
    session.add(
        SRITransmission(
            tenant_id=tenant_id,
            sales_document_id=document.id,
            access_key=document.access_key or "",
            status="AUTHORIZED",
            messages=[{"source": "sky-franquicia", "historical": True}],
            attempts=0,
            authorization_number=document.authorization_number,
            authorized_at=document.authorized_at,
        )
    )
    xml_upload = await storage.upload_artifact(
        tenant_id=str(tenant_id),
        document_id=str(document.id),
        artifact_type="xml-signed",
        version=1,
        data=str(row["sri_xml"]).encode(),
    )
    session.add(
        DocumentArtifact(
            tenant_id=tenant_id,
            sales_document_id=document.id,
            artifact_type="xml-signed",
            object_key=xml_upload.object_key,
            sha256=xml_upload.sha256,
            version=1,
        )
    )
    receivable = Receivable(
        tenant_id=tenant_id,
        sales_document_id=document.id,
        party_id=party.id,
        original_amount=document.total,
        currency="USD",
        status="OPEN",
    )
    session.add(receivable)
    await session.flush()
    session.add(
        ReceivableInstallment(
            tenant_id=tenant_id,
            receivable_id=receivable.id,
            sequence=1,
            due_date=issue_date,
            amount=document.total,
        )
    )
    await _advance_sequence(
        session,
        tenant_id=tenant_id,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=document.sequential,
    )
    context = _migration_context(tenant_id)
    source_reference = _source_reference(str(row["id"]))
    await append_audit(
        session,
        context=context,
        action="sales_document.migrated_from_sky",
        entity_type="sales_document",
        entity_id=str(document.id),
        correlation_id=correlation_id,
        idempotency_key=f"sky-authorized:{source_reference}",
        details={
            "source_reference": source_reference,
            "access_key_sha256": hashlib.sha256((document.access_key or "").encode()).hexdigest(),
            "status": "AUTHORIZED",
            "receivable_created": True,
        },
    )
    return str(document.id)


async def load_authorized_invoices(
    *, session: AsyncSession, source_url: str, ruc: str, tenant_id: str
) -> dict[str, Any]:
    """Load eligible authorized Sky invoices into one IAERP tenant.

    This is an intentional migration exception, not an invoice-issuance flow:
    it never calls SRI, never creates a payment or reminder, and preserves the
    source access key, authorization and signed XML.  Invalid source rows are
    skipped individually so a missing artifact cannot block complete records.
    """

    target_tenant_id = uuid.UUID(tenant_id)
    rows = await extract_authorized_source_invoices(source_url=source_url, ruc=ruc)
    loaded = 0
    already_loaded = 0
    skipped: list[dict[str, str]] = []
    correlation_id = str(uuid.uuid4())
    async with session.begin():
        tenant = await session.scalar(
            select(Tenant).where(Tenant.id == target_tenant_id).with_for_update()
        )
        if tenant is None or tenant.ruc != ruc or not tenant.active:
            raise ValueError("Target tenant is not active or does not match the requested RUC.")
        for row in rows:
            reference = _source_reference(str(row["id"]))
            issues = validate_source_invoices([row])
            if issues:
                skipped.append({"source_reference": reference, "reason": issues[0].code})
                continue
            access_key = str(row["sri_access_key"])
            existing = await session.scalar(
                select(SalesDocument)
                .where(SalesDocument.access_key == access_key)
                .with_for_update()
            )
            if existing is not None:
                if existing.tenant_id != target_tenant_id:
                    raise ValueError("An authorized source access key belongs to another tenant.")
                already_loaded += 1
                continue
            payload = {"source_reference": reference, "access_key": access_key}
            record = await session.scalar(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.tenant_id == target_tenant_id,
                    IdempotencyRecord.actor_id == _MIGRATION_ACTOR_ID,
                    IdempotencyRecord.operation == _MIGRATION_OPERATION,
                    IdempotencyRecord.idempotency_key == access_key,
                )
                .with_for_update()
            )
            if record is not None and record.status == "COMPLETED":
                already_loaded += 1
                continue
            request_hash = canonical_hash(payload)
            if record is None:
                record = IdempotencyRecord(
                    tenant_id=target_tenant_id,
                    actor_id=_MIGRATION_ACTOR_ID,
                    operation=_MIGRATION_OPERATION,
                    idempotency_key=access_key,
                    request_hash=request_hash,
                    status="PROCESSING",
                    expires_at=datetime(2099, 1, 1, tzinfo=UTC),
                )
                session.add(record)
                await session.flush()
            elif record.request_hash != request_hash:
                raise ValueError("Migration idempotency key conflicts with different source data.")
            try:
                document_id = await _load_authorized_row(
                    session,
                    tenant_id=target_tenant_id,
                    row=row,
                    correlation_id=correlation_id,
                )
            except ValueError as error:
                await session.delete(record)
                skipped.append({"source_reference": reference, "reason": str(error)[:160]})
                continue
            record.status = "COMPLETED"
            record.response_status = 201
            record.response_body = {"sales_document_id": document_id}
            loaded += 1
    return {
        "tenant_id": tenant_id,
        "source_ruc": ruc,
        "authorized_read": len(rows),
        "loaded": loaded,
        "already_loaded": already_loaded,
        "skipped": skipped,
        "payments_created": 0,
        "sri_calls": 0,
    }


async def build_dry_run_report(
    *, session: AsyncSession, source_url: str, ruc: str, tenant_id: str
) -> dict[str, Any]:
    """Return a non-sensitive migration report without persisting source data."""

    rows = await extract_source_invoices(source_url=source_url, ruc=ruc)
    issues = validate_source_invoices(rows)
    source_keys = [row["sri_access_key"] for row in rows if row.get("sri_access_key")]
    existing_keys: set[str] = set()
    if source_keys:
        existing = await session.execute(
            text(
                """
                SELECT access_key
                FROM sales_documents
                WHERE tenant_id = :tenant_id AND access_key = ANY(:access_keys)
                """
            ),
            {"tenant_id": tenant_id, "access_keys": source_keys},
        )
        existing_keys = {row[0] for row in existing.all()}

    statuses = Counter((row.get("status") or "NULL").upper() for row in rows)
    total = sum((_decimal(row.get("total")) for row in rows), Decimal("0.00"))
    report = {
        "source_ruc": ruc,
        "tenant_id": tenant_id,
        "read": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "invoice_total": str(total),
        "existing_access_key_collisions": len(existing_keys),
        "issues": [asdict(issue) for issue in issues],
        "ready_to_load": not issues and not existing_keys,
    }
    return report

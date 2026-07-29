"""Read-only validation for historical invoices from Sky Franquicia.

The first migration gate intentionally does not persist source records.  It
produces an aggregate report and rejects data that cannot be represented
faithfully in IAERP.  In particular, it never calls SRI and never emits a
document in the destination.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

_SUPPORTED_SOURCE_STATUSES = frozenset({"AUTHORIZED", "CANCELLED"})
_MONEY_QUANTUM = Decimal("0.01")


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
            source_subtotal = _decimal(row.get("subtotal_15")) + _decimal(
                row.get("subtotal_0")
            ) - _decimal(row.get("discount"))
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

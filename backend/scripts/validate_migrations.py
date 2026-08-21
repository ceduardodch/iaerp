from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def database_url() -> URL:
    url = make_url(os.environ["DATABASE_URL"])
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Migration validation requires PostgreSQL.")
    if not url.database or not SAFE_DATABASE_NAME.fullmatch(url.database):
        raise RuntimeError("DATABASE_URL must contain a simple database name.")
    if not url.database.endswith("_migrations"):
        raise RuntimeError("Refusing to reset a database not ending in '_migrations'.")
    return url


async def admin_connection(url: URL) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=os.environ.get("POSTGRES_ADMIN_DATABASE", "postgres"),
    )


async def reset_database(url: URL) -> None:
    connection = await admin_connection(url)
    try:
        await connection.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1 AND pid <> pg_backend_pid()
            """,
            url.database,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{url.database}"')
        await connection.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await connection.close()


async def assert_downgraded_to_base(url: URL) -> None:
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        tables = await connection.fetch(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename <> 'alembic_version'
            ORDER BY tablename
            """
        )
    finally:
        await connection.close()
    if tables:
        names = ", ".join(row["tablename"] for row in tables)
        raise RuntimeError(f"Downgrade left application tables behind: {names}")


async def assert_analytic_classification_insert(url: URL) -> None:
    """Prove migrated tables can apply their timestamp defaults on a real insert."""
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        await connection.execute(
            """
            INSERT INTO tenants (ruc, name, organization_id, active, id)
            VALUES (
                '1799999999001',
                'Migration validation tenant',
                'migration-validation',
                true,
                '11111111-1111-4111-8111-111111111111'
            )
            """
        )
        row = await connection.fetchrow(
            """
            INSERT INTO analytic_classifications (
                code, name, max_depth, active, id, tenant_id
            )
            VALUES (
                'VALIDATION',
                'Migration validation',
                1,
                true,
                '22222222-2222-4222-8222-222222222222',
                '11111111-1111-4111-8111-111111111111'
            )
            RETURNING created_at, updated_at
            """
        )
    finally:
        await connection.close()
    if row is None or row["created_at"] is None or row["updated_at"] is None:
        raise RuntimeError("Analytic classification timestamp defaults are missing.")


async def seed_missing_tax_detail(url: URL) -> None:
    """Create the legacy state fixed by the migration at the previous head."""
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        await connection.execute(
            """
            INSERT INTO tenants (ruc, name, organization_id, active, id)
            VALUES (
                '1788888888001',
                'Tax migration tenant',
                'tax-migration-validation',
                true,
                '33333333-3333-4333-8333-333333333333'
            );
            INSERT INTO tax_periods (
                id, tenant_id, year, month, obligation_type, status
            ) VALUES (
                '44444444-4444-4444-8444-444444444444',
                '33333333-3333-4333-8333-333333333333',
                2026,
                7,
                'IVA',
                'LISTO_REVISAR'
            );
            INSERT INTO fiscal_documents (
                id, tenant_id, tax_period_id, direction, doc_type, access_key,
                issue_date, subtotal, tax_total, total, is_preliminary
            ) VALUES (
                '55555555-5555-4555-8555-555555555555',
                '33333333-3333-4333-8333-333333333333',
                '44444444-4444-4444-8444-444444444444',
                'RECIBIDO',
                'FACTURA',
                '0107202601178888888800120010010000000011234567811',
                '2026-07-01',
                100.00,
                15.00,
                115.00,
                false
            );
            INSERT INTO payables (
                id, tenant_id, fiscal_document_id, description, issue_date,
                due_date, total, evidence_status
            ) VALUES (
                '66666666-6666-4666-8666-666666666666',
                '33333333-3333-4333-8333-333333333333',
                '55555555-5555-4555-8555-555555555555',
                'Legacy TXT purchase without tax brackets',
                '2026-07-01',
                '2026-07-01',
                115.00,
                'FISCAL_XML'
            );
            INSERT INTO tax_tasks (
                id, tenant_id, tax_period_id, task_type, title, status,
                requires_approval
            ) VALUES (
                '77777777-7777-4777-8777-777777777777',
                '33333333-3333-4333-8333-333333333333',
                '44444444-4444-4444-8444-444444444444',
                'PREPARAR_ATS',
                'Legacy task created from incomplete evidence',
                'PENDIENTE',
                true
            )
            """
        )
    finally:
        await connection.close()


async def assert_missing_tax_detail_backfill(url: URL) -> None:
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        row = await connection.fetchrow(
            """
            SELECT document.is_preliminary, payable.evidence_status, period.status,
                   task.status AS task_status
            FROM fiscal_documents AS document
            JOIN payables AS payable
              ON payable.tenant_id = document.tenant_id
             AND payable.fiscal_document_id = document.id
            JOIN tax_periods AS period
             ON period.tenant_id = document.tenant_id
             AND period.id = document.tax_period_id
            JOIN tax_tasks AS task
              ON task.tenant_id = document.tenant_id
             AND task.tax_period_id = period.id
            WHERE document.id = '55555555-5555-4555-8555-555555555555'
            """
        )
    finally:
        await connection.close()
    if row is None or row["is_preliminary"] is not True:
        raise RuntimeError("Fiscal documents without tax detail were not marked preliminary.")
    if row["evidence_status"] != "PRELIMINARY":
        raise RuntimeError("The linked payable still claims to have fiscal XML detail.")
    if row["status"] != "EVIDENCIA_INCOMPLETA":
        raise RuntimeError("The affected tax period was not reopened as incomplete evidence.")
    if row["task_status"] != "DESCARTADO":
        raise RuntimeError("An ATS task remained open for incomplete evidence.")


def alembic(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        check=True,
    )


def main() -> None:
    url = database_url()
    asyncio.run(reset_database(url))
    alembic("upgrade", "d0e1f2a3b4c5")  # pragma: allowlist secret
    asyncio.run(seed_missing_tax_detail(url))
    alembic("upgrade", "head")
    asyncio.run(assert_missing_tax_detail_backfill(url))
    asyncio.run(assert_analytic_classification_insert(url))
    alembic("downgrade", "base")
    asyncio.run(assert_downgraded_to_base(url))
    alembic("upgrade", "head")
    alembic("check")
    print("Alembic clean install, downgrade/upgrade and check passed.")


if __name__ == "__main__":
    main()

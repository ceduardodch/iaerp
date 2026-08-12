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
    alembic("upgrade", "head")
    asyncio.run(assert_analytic_classification_insert(url))
    alembic("downgrade", "base")
    asyncio.run(assert_downgraded_to_base(url))
    alembic("upgrade", "head")
    alembic("check")
    print("Alembic clean install, downgrade/upgrade and check passed.")


if __name__ == "__main__":
    main()

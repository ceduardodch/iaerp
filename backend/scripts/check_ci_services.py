from __future__ import annotations

import asyncio
import os

import asyncpg  # type: ignore[import-untyped]
from redis.asyncio import Redis
from sqlalchemy.engine import make_url


async def check_postgres() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    connection = await asyncpg.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        assert await connection.fetchval("SELECT 1") == 1
    finally:
        await connection.close()


async def check_redis() -> None:
    client = Redis.from_url(os.environ["REDIS_URL"])
    try:
        assert await client.ping()
    finally:
        await client.aclose()


async def main() -> None:
    await asyncio.gather(check_postgres(), check_redis())
    print("PostgreSQL and Redis are reachable.")


if __name__ == "__main__":
    asyncio.run(main())

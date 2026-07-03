from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

settings = get_settings()


async def readiness() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        if not await redis.ping():
            raise RuntimeError("Redis ping failed")
    finally:
        await redis.aclose()

    return {"database": "ok", "redis": "ok"}


async def startup_readiness() -> dict[str, str]:
    dependencies = await readiness()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1 FROM tenants LIMIT 1"))
    return {
        **dependencies,
        "schema": "ok",
        "auth": settings.AUTH_MODE,
        "environment": settings.APP_ENV,
    }

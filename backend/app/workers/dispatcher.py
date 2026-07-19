import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.workers.celery_app import celery_app
from app.workers.collections import run_collection_scheduler
from app.workers.outbox import OutboxMessage, run_dispatcher

settings = get_settings()


class CeleryPublisher:
    async def publish(self, message: OutboxMessage) -> None:
        await asyncio.to_thread(
            celery_app.send_task,
            "iaerp.consume_event",
            kwargs={
                "event_id": str(message.event_id),
                "tenant_id": str(message.tenant_id),
                "event_type": message.event_type,
                "aggregate_type": message.aggregate_type,
                "aggregate_id": message.aggregate_id,
                "payload": message.payload,
                "correlation_id": message.correlation_id,
                "attempts": message.attempts,
            },
            task_id=str(message.event_id),
        )


async def publish_heartbeat() -> None:
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        while True:
            await client.set(
                settings.DISPATCHER_HEARTBEAT_KEY,
                "ok",
                ex=settings.DISPATCHER_HEARTBEAT_TTL_SECONDS,
            )
            await asyncio.sleep(settings.DISPATCHER_HEARTBEAT_TTL_SECONDS / 3)
    finally:
        await client.aclose()


async def serve() -> None:
    async with asyncio.TaskGroup() as group:
        group.create_task(run_dispatcher(CeleryPublisher()))
        group.create_task(publish_heartbeat())
        group.create_task(run_collection_scheduler())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()

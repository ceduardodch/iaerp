import asyncio

from app.workers.celery_app import celery_app
from app.workers.outbox import OutboxMessage, run_dispatcher


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


def main() -> None:
    asyncio.run(run_dispatcher(CeleryPublisher()))


if __name__ == "__main__":
    main()

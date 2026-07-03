import argparse

from redis import Redis

from app.core.config import get_settings
from app.workers.celery_app import celery_app

settings = get_settings()


def check_worker() -> None:
    responses = celery_app.control.inspect(timeout=3).ping()
    if not responses or not any(response.get("ok") == "pong" for response in responses.values()):
        raise SystemExit("Celery worker did not answer ping")


def check_dispatcher() -> None:
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        if client.get(settings.DISPATCHER_HEARTBEAT_KEY) != "ok":
            raise SystemExit("Outbox dispatcher heartbeat is missing")
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("worker", "dispatcher"))
    args = parser.parse_args()
    if args.component == "worker":
        check_worker()
    else:
        check_dispatcher()


if __name__ == "__main__":
    main()

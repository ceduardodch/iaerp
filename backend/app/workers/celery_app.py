from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "iaerp",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    timezone="America/Guayaquil",
    enable_utc=True,
)

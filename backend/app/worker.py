"""Celery application for long-running connector and evidence jobs.

The customer POC executes connector runs synchronously for transparent demos.
Production deployments can route those calls through this worker without
changing the connector adapter contracts.
"""
from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery(
    "jsan_geodiscover",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="geodiscover.health_ping")
def health_ping() -> dict[str, str]:
    return {"status": "healthy", "service": "JSAN GeoDiscover worker"}

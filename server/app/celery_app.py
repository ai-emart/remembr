"""Celery application instance and configuration."""

from __future__ import annotations

from celery import Celery

from app.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    redis_url = settings.redis_url.get_secret_value()

    app = Celery(
        "remembr",
        broker=redis_url,
        backend=redis_url,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # Beat schedule placeholder — populated in a future task
        beat_schedule={},
    )
    return app


celery_app = create_celery_app()

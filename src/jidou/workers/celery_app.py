"""Celery application for background task processing."""

import logging

from celery import Celery

from jidou.config import settings

logger = logging.getLogger(__name__)

# Create Celery application
celery_app = Celery(
    settings.app_name,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=3600,  # Hard timeout: 1 hour
    task_soft_time_limit=3000,  # Soft timeout: 50 minutes
    task_default_queue="jidou",
    task_routes={
        "jidou.workers.download_tasks.*": {"queue": "jidou.download"},
        "jidou.workers.scan_tasks.*": {"queue": "jidou.scan"},
        "jidou.workers.match_tasks.*": {"queue": "jidou.match"},
        "jidou.workers.sync_tasks.*": {"queue": "jidou.sync"},
    },
    worker_max_tasks_per_child=100,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["jidou.workers"])

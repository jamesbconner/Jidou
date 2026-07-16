"""Celery application for background task processing."""

import logging

from celery import Celery
from celery.schedules import crontab

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
    # task_acks_late means a task's ack is withheld until it finishes. The
    # Redis transport's default visibility_timeout is 3600s — if a message
    # isn't acked within that window, Redis assumes the worker died and
    # redelivers it to another worker, even if the original is still running.
    # path_import_task and sync_all_task both override their time_limit to
    # 25200s (7h; see import_tasks.py / sync_tasks.py), which is far longer
    # than the 3600s default, so a single legitimate run would get
    # redelivered and re-executed from scratch roughly every hour, racing
    # against itself on the same DB rows.
    # This must stay comfortably above the longest task-level time_limit
    # override anywhere in the app.
    broker_transport_options={"visibility_timeout": 43200},  # 12 hours
    task_default_queue="jidou",
    worker_max_tasks_per_child=100,
    include=[
        "jidou.workers.tasks",
        "jidou.workers.download_tasks",
        "jidou.workers.scan_tasks",
        "jidou.workers.match_tasks",
        "jidou.workers.route_tasks",
        "jidou.workers.sync_tasks",
        "jidou.workers.import_tasks",
        "jidou.workers.db_import_tasks",
        "jidou.workers.rss_tasks",
        "jidou.workers.seed_tasks",
        "jidou.workers.scheduled_tasks",
    ],
)

# ---------------------------------------------------------------------------
# Beat schedule — built from env-var settings at startup; restart to change.
# Each enabled schedule fires the thin overlap-guard wrapper task, which
# checks for an already-active run before dispatching the real worker task.
# ---------------------------------------------------------------------------
_beat_schedule: dict[str, object] = {}

if settings.sync_schedule_enabled:
    _beat_schedule["scheduled-sync"] = {
        "task": "jidou.workers.scheduled_tasks.scheduled_sync_task",
        "schedule": crontab(hour=settings.sync_schedule_hours, minute="0"),
        "options": {"queue": "jidou"},
    }
    logger.info(
        "Sync beat schedule enabled: daily at hour(s) %s UTC",
        settings.sync_schedule_hours,
    )

if settings.rss_import_schedule_enabled:
    _beat_schedule["scheduled-rss-import"] = {
        "task": "jidou.workers.scheduled_tasks.scheduled_rss_import_task",
        "schedule": crontab(hour=settings.rss_import_schedule_hours, minute="0"),
        "options": {"queue": "jidou"},
    }
    logger.info(
        "RSS import beat schedule enabled: daily at hour(s) %s UTC",
        settings.rss_import_schedule_hours,
    )

celery_app.conf.beat_schedule = _beat_schedule

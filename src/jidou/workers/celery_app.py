"""Celery application for background task processing."""

import logging
from typing import Final

from celery import Celery
from celery.schedules import crontab

from jidou.config import settings

logger = logging.getLogger(__name__)

# Time limits for the two tasks that legitimately run for hours, overriding the
# app-wide 50min/60min defaults below (hard 7h, soft 6h).
# - sync_all_task chains scan, download, match and route sequentially in one
#   execution. Scan is fast after the first run, download is bandwidth-bound,
#   match is sequential per-file LLM parsing. On any real backlog the combined
#   time exceeds the default meant for a single phase, so sync would hit
#   SoftTimeLimitExceeded well before it is actually stuck.
# - path_import_task can span hundreds of previously-unseen shows, each needing
#   several sequential TMDB calls (search, details, external IDs, episode groups,
#   per-season episode sync, alias generation) serialized behind the TMDB rate
#   limit (1 call/2s). A few hundred new shows can take multiple hours.
# broker_transport_options["visibility_timeout"] below must stay comfortably
# above time_limit here.
LONG_TASK_LIMITS: Final[dict[str, int]] = {"time_limit": 25200, "soft_time_limit": 21600}

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
    # 25200s (7h; see LONG_TASK_LIMITS), which is far longer
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
        "jidou.workers.backfill_tasks",
        "jidou.workers.image_cache_tasks",
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

if settings.image_cache_expiration_enabled:
    _beat_schedule["purge-stale-images"] = {
        "task": "jidou.workers.image_cache_tasks.purge_stale_images_task",
        "schedule": crontab(hour="3", minute="30"),
        "options": {"queue": "jidou"},
    }
    logger.info(
        "Image cache purge beat schedule enabled: daily at 03:30 UTC (retention %d days)",
        settings.image_cache_retention_days,
    )

celery_app.conf.beat_schedule = _beat_schedule

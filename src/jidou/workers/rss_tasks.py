"""Celery tasks for RSS config import and publish operations."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.rss_import_orchestrator import RssImportOrchestrator
from jidou.services.progress import (
    TaskCancelledError,
    append_task_event,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


def _build_sftp() -> SFTPService:
    """Instantiate SFTPService from application settings."""
    return SFTPService(
        host=settings.sftp_host or "",
        port=settings.sftp_port,
        username=settings.sftp_username,
        password=settings.sftp_password,
        key_path=settings.sftp_key_path,
        known_hosts=None,
        max_workers=settings.sftp_max_workers,
        max_retries=settings.sftp_max_retries,
        retry_delay=settings.sftp_retry_delay,
    )


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def rss_import_task(  # type: ignore[no-untyped-def]
    self,
    dry_run: bool = False,
) -> str:
    """Download the remote YaRSS2 config and sync it into the database.

    Args:
        self: Celery request context.
        dry_run: Parse without writing to the database.

    Returns:
        The Celery task ID.
    """
    try:
        return asyncio.run(_rss_import(self.request.id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _rss_import(celery_task_id: str, dry_run: bool) -> str:
    """Async implementation of the RSS import task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import_error: str | None = None  # set on orchestrator-level failure; raised post-session

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session,
                celery_task_id,
                "rss_import",
                progress_total=0,
                dry_run=dry_run,
            )
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                logger.info("Task %s already %s; skipping redelivery", celery_task_id, task.status)
                return celery_task_id

            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_message="Downloading RSS config…",
            )

            async def on_event(level: str, msg: str, ctx: dict[str, object] | None = None) -> None:
                async with session_factory() as event_session:
                    await append_task_event(event_session, celery_task_id, level, msg, ctx)

            sftp = _build_sftp()
            orchestrator = RssImportOrchestrator(
                session=session,
                sftp=sftp,
                remote_path=settings.rss_config_remote_path or "",
                dry_run=dry_run,
                on_event=on_event,
            )

            import_result = await orchestrator.run()

            if import_result.errors:
                error_summary = "; ".join(import_result.errors)
                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.FAILED,
                    progress_message=f"Import failed: {error_summary}",
                    result_summary={"errors": import_result.errors, "dry_run": dry_run},
                )
                import_error = error_summary  # raised after session exits so Celery sees failure
            else:
                summary: dict[str, object] = {
                    "feeds_created": import_result.feeds_created,
                    "feeds_updated": import_result.feeds_updated,
                    "subscriptions_created": import_result.subscriptions_created,
                    "subscriptions_updated": import_result.subscriptions_updated,
                    "subscriptions_remote_deleted": import_result.subscriptions_remote_deleted,
                    "shows_linked": import_result.shows_linked,
                    "snapshot_id": import_result.snapshot_id,
                    "errors": import_result.errors,
                    "dry_run": dry_run,
                }

                final_task = await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.COMPLETED,
                    progress_message=(
                        f"Done — {import_result.feeds_created} feeds created, "
                        f"{import_result.subscriptions_created} subscriptions created, "
                        f"{import_result.subscriptions_updated} updated"
                    ),
                    result_summary=summary,
                )

                if final_task is not None and final_task.status == TaskStatus.COMPLETED.value:
                    await emit_progress(
                        {
                            "celery_task_id": celery_task_id,
                            "type": "complete",
                            "data": {"summary": summary},
                        }
                    )

    except TaskCancelledError:
        logger.info("RSS import task %s was cancelled", celery_task_id)
    except Exception as exc:
        logger.exception("RSS import task %s failed", celery_task_id)
        error_msg = str(exc) or type(exc).__name__
        async with session_factory() as session:
            await append_task_event(session, celery_task_id, "error", f"Task failed: {error_msg}")
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message=f"Failed: {error_msg}",
            )
        await emit_progress(
            {
                "celery_task_id": celery_task_id,
                "type": "error",
                "data": {"error": error_msg},
            }
        )
        raise
    finally:
        await engine.dispose()

    if import_error is not None:
        raise RuntimeError(f"Import failed: {import_error}")

    return celery_task_id

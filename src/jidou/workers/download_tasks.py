"""Celery tasks for downloading files from remote SFTP."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.download_orchestrator import DownloadOrchestrator
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)
from jidou.services.sftp_service import SFTPService

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def download_files_task(  # type: ignore[no-untyped-def]
    self,
    show_id: int,
    dry_run: bool = False,
) -> str:
    """Download files for a show from remote SFTP.

    Args:
        self: Celery request context for retries.
        show_id: Database ID of the show to download.
        dry_run: Simulate without actually downloading.

    Returns:
        The celery task ID.
    """
    try:
        return asyncio.run(_download_files(self.request.id, show_id, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _download_files(
    celery_task_id: str,
    show_id: int,
    dry_run: bool = False,
) -> str:
    """Async implementation of the download task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session, celery_task_id, "download", progress_total=0, dry_run=dry_run
            )
            # Redelivered Celery messages must not rerun finished work.
            if task.status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                logger.info("Task %s already %s; skipping redelivery", celery_task_id, task.status)
                return celery_task_id
            sftp = SFTPService(
                host=settings.sftp_host or "",
                port=settings.sftp_port,
                username=settings.sftp_username,
                password=settings.sftp_password,
                key_path=settings.sftp_key_path,
                remote_base_path=settings.sftp_remote_base_path,
                known_hosts=None,
            )

            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Starting download..."
            )

            async def on_progress(current: int, total: int, message: str) -> None:
                await check_task_cancelled(session, celery_task_id)
                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=current,
                    progress_total=total,
                    progress_message=message,
                )
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "progress",
                        "data": {"current": current, "total": total, "message": message},
                    }
                )

            result = await DownloadOrchestrator(session, sftp).run(
                show_id=show_id, dry_run=dry_run, on_progress=on_progress
            )

            # Mark complete — gate the WebSocket event on the DB update landing.
            # If the row was concurrently cancelled, update_task_status returns
            # it unchanged (status still CANCELLED) and we must not emit "complete".
            total_processed = result.files_downloaded + result.files_failed + result.files_skipped
            completed = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_processed,
                progress_total=total_processed,
                progress_message=f"Download complete: {result.files_downloaded} files",
                result_summary={
                    "files_downloaded": result.files_downloaded,
                    "bytes_downloaded": result.bytes_downloaded,
                    "files_failed": result.files_failed,
                    "dry_run": dry_run,
                },
            )
            if completed is not None and completed.status == TaskStatus.COMPLETED.value:
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "complete",
                        "data": {
                            "summary": {
                                "files_downloaded": result.files_downloaded,
                                "dry_run": dry_run,
                            }
                        },
                    }
                )

        return celery_task_id

    except TaskCancelledError:
        logger.info("Download task cancelled")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.CANCELLED,
                progress_message="Task cancelled",
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "cancelled",
                    "data": {},
                }
            )
        return celery_task_id
    except Exception as exc:
        logger.exception("Download task failed")
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message=str(exc),
            )
            await emit_progress(
                {
                    "celery_task_id": celery_task_id,
                    "type": "error",
                    "data": {"error": str(exc)},
                }
            )
        raise
    finally:
        await engine.dispose()

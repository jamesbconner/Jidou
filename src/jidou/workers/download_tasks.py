"""Celery tasks for downloading files from remote SFTP."""

import asyncio
import logging

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.services.progress import create_task_record, emit_progress, update_task_status

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
    return asyncio.run(_download_files(self.request.id, show_id, dry_run))


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
            # Create task record
            await create_task_record(
                session, celery_task_id, "download", progress_total=0, dry_run=dry_run
            )
            await update_task_status(
                session, celery_task_id, TaskStatus.RUNNING, progress_message="Starting download..."
            )

            # TODO: Implement SFTP download logic
            # For now, simulate progress
            total_files = 10  # Placeholder
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=total_files,
                progress_message="Downloading files...",
            )

            for i in range(1, total_files + 1):
                if dry_run:
                    await emit_progress(
                        {
                            "celery_task_id": celery_task_id,
                            "type": "progress",
                            "data": {
                                "current": i,
                                "total": total_files,
                                "message": f"[DRY RUN] Would download file {i}/{total_files}",
                            },
                        }
                    )
                else:
                    await emit_progress(
                        {
                            "celery_task_id": celery_task_id,
                            "type": "progress",
                            "data": {
                                "current": i,
                                "total": total_files,
                                "message": f"Downloading file {i}/{total_files}",
                            },
                        }
                    )

                await update_task_status(
                    session,
                    celery_task_id,
                    TaskStatus.RUNNING,
                    progress_current=i,
                    progress_message=f"Downloaded {i}/{total_files} files",
                )

                # Simulate work
                await asyncio.sleep(0.1)

            # Mark complete
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total_files,
                progress_message="Download complete",
                result_summary={"files_downloaded": total_files, "dry_run": dry_run},
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
        raise
    finally:
        await engine.dispose()

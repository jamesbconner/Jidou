"""Celery task for importing NAS episode file lists into the database."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.nas_import_orchestrator import NASImportOrchestrator
from jidou.services.nas_parser import parse_file
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def nas_import_task(  # type: ignore[no-untyped-def]
    self,
    file_content: str,
    content_type: str = "anime",
    dry_run: bool = False,
) -> str:
    """Import a NAS episode path file, creating shows and marking episodes tracked.

    Args:
        self: Celery request context.
        file_content: Full text content of the path file.
        content_type: Content type assigned to newly created shows
            (``"anime"``, ``"tv"``, or ``"movie"``).
        dry_run: Parse and match without writing to the database.

    Returns:
        The Celery task ID.
    """
    try:
        return asyncio.run(_nas_import(self.request.id, file_content, content_type, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _nas_import(
    celery_task_id: str,
    file_content: str,
    content_type: str,
    dry_run: bool,
) -> str:
    """Async implementation of the NAS import task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session,
                celery_task_id,
                "import",
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
                progress_message="Parsing file…",
            )

            entries = parse_file(file_content)
            total_shows = len({e.show_dir for e in entries})

            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=total_shows,
                progress_message=f"Found {total_shows} unique show(s) in {len(entries)} entries",
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

            tmdb = TMDBService()
            orchestrator = NASImportOrchestrator(
                session, tmdb, content_type=content_type, dry_run=dry_run
            )
            import_result = await orchestrator.run(entries, on_progress=on_progress)

            summary: dict[str, object] = {
                "shows_processed": import_result.shows_processed,
                "shows_created": import_result.shows_created,
                "shows_found": import_result.shows_found,
                "shows_not_found": import_result.shows_not_found,
                "episodes_tracked": import_result.episodes_tracked,
                "episodes_unmatched": import_result.episodes_unmatched,
                "show_results": [
                    {
                        "show_dir": r.show_dir,
                        "tmdb_id": r.tmdb_id,
                        "tmdb_title": r.tmdb_title,
                        "action": r.action,
                        "episodes_tracked": r.episodes_tracked,
                        "episodes_unmatched": r.episodes_unmatched,
                    }
                    for r in import_result.show_results
                ],
                "dry_run": dry_run,
            }

            final_task = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=import_result.shows_processed,
                progress_total=import_result.shows_processed,
                progress_message=(
                    f"Done — {import_result.shows_created} created, "
                    f"{import_result.shows_found} found, "
                    f"{import_result.episodes_tracked} episodes tracked"
                ),
                result_summary=summary,
            )

            # Only emit "complete" if the row actually reached COMPLETED — a
            # concurrent cancel between the last check and here takes precedence.
            if final_task is not None and final_task.status == TaskStatus.COMPLETED.value:
                await emit_progress(
                    {
                        "celery_task_id": celery_task_id,
                        "type": "complete",
                        "data": {"summary": summary},
                    }
                )

    except TaskCancelledError:
        logger.info("NAS import task %s was cancelled", celery_task_id)
    except Exception:
        logger.exception("NAS import task %s failed", celery_task_id)
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message="Import failed — see logs",
            )
        await emit_progress(
            {
                "celery_task_id": celery_task_id,
                "type": "error",
                "data": {"error": "NAS import failed"},
            }
        )
        raise  # Let Celery record the job as failed and honour retry/DLQ policy.
    finally:
        await engine.dispose()

    return celery_task_id

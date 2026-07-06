"""Celery task for importing episode file path lists into the database."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
from jidou.services.llm_service import create_llm_service
from jidou.services.path_parser import parse_file
from jidou.services.progress import (
    TaskCancelledError,
    append_task_event,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)


# Overrides the app-wide 50min/60min limits (celery_app.py) for this task
# specifically. A bulk path-list import can span hundreds of previously-unseen
# shows, each requiring several sequential TMDB calls (search, details,
# external IDs, episode groups, per-season episode sync, alias generation) —
# all serialized behind TMDB_RATE_LIMIT_PER_SECOND (default: 1 call/2s per
# CLAUDE.md's rate-limiting policy). A few hundred new shows can legitimately
# take multiple hours, well past the global default meant for quick,
# single-file-scoped tasks (route/match/scan/sync).
@shared_task(bind=True, time_limit=25200, soft_time_limit=21600)  # type: ignore[untyped-decorator]
def path_import_task(  # type: ignore[no-untyped-def]
    self,
    file_content: str,
    content_type: str = "anime",
    dry_run: bool = False,
) -> str:
    """Import an episode path file, creating shows and marking episodes tracked.

    Accepts both Windows-style (``Z:\\...``) and POSIX-style (``/mnt/...``)
    absolute paths; format is detected automatically per line.

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
        return asyncio.run(_path_import(self.request.id, file_content, content_type, dry_run))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _path_import(
    celery_task_id: str,
    file_content: str,
    content_type: str,
    dry_run: bool,
) -> str:
    """Async implementation of the path-file import task."""
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

            # parse_file() never raises — an unparseable line is simply skipped
            # (e.g. wrong encoding, unexpected format) — so a file that's
            # clearly non-trivial but yields zero entries would otherwise
            # complete silently with all-zero counts and no indication why.
            nontrivial_lines = sum(1 for line in file_content.splitlines() if line.strip())
            if not entries and nontrivial_lines > 0:
                warning = (
                    f"Parsed 0 usable entries from {nontrivial_lines} non-blank line(s) — "
                    "check the file's encoding (UTF-16 exports from PowerShell's `>` "
                    "redirection are a common cause) and that each line is an absolute "
                    "path ending in a recognized media extension."
                )
                logger.warning("Path import %s: %s", celery_task_id, warning)
                await append_task_event(session, celery_task_id, "warn", warning)

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
            llm = create_llm_service(settings)

            async def on_event(level: str, msg: str, ctx: dict[str, object] | None = None) -> None:
                # Use a separate session so the event commit does not flush
                # pending show/episode state from the orchestrator's session.
                # Without this, append_task_event's session.commit() would
                # commit partially-created shows mid-import, preventing clean
                # rollback on failure.
                async with session_factory() as event_session:
                    await append_task_event(event_session, celery_task_id, level, msg, ctx)

            orchestrator = PathImportOrchestrator(
                session,
                tmdb,
                content_type=content_type,
                dry_run=dry_run,
                llm=llm,
                on_event=on_event,
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
                        "unmatched_paths": r.unmatched_paths,
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
        logger.info("Path import task %s was cancelled", celery_task_id)
    except Exception as exc:
        logger.exception("Path import task %s failed", celery_task_id)
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
        raise  # Let Celery record the job as failed and honour retry/DLQ policy.
    finally:
        await engine.dispose()

    return celery_task_id

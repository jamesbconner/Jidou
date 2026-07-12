"""Celery task for importing episode file path lists into the database."""

import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings
from jidou.models.task import TaskStatus
from jidou.orchestrators.path_import_orchestrator import PathImportOrchestrator
from jidou.services.llm_service import create_llm_service
from jidou.services.path_parser import parse_file
from jidou.services.progress import append_task_event, mark_task_timed_out, update_task_status
from jidou.services.tmdb import TMDBService
from jidou.workers._harness import EventFn, ProgressFn, WorkflowResult, run_task_workflow

logger = logging.getLogger(__name__)


def _host_root_for_content_type(content_type: str) -> str:
    """Return the configured host-side library root for a content type.

    Mirrors the container-side mapping in
    :func:`jidou.api.routes.shows._auto_local_path`, but for the host path —
    the import file's raw paths are Windows/POSIX host paths, not
    container-internal ones.

    Args:
        content_type: One of ``"anime"``, ``"movie"``, or ``"tv"``.

    Returns:
        The configured host path string for that content type.
    """
    if content_type == "movie":
        return settings.local_movie_host_path
    if content_type == "anime":
        return settings.local_anime_host_path
    return settings.local_tv_host_path


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
    mode: str = "full",
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
        mode: ``"full"``, ``"shows_only"``, or ``"episodes_only"`` — see
            :class:`~jidou.orchestrators.path_import_orchestrator.PathImportOrchestrator`.

    Returns:
        The Celery task ID.
    """
    try:
        return asyncio.run(_path_import(self.request.id, file_content, content_type, dry_run, mode))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _path_import(
    celery_task_id: str,
    file_content: str,
    content_type: str,
    dry_run: bool,
    mode: str = "full",
) -> str:
    """Async implementation of the path-file import task."""

    async def _work(
        session: AsyncSession, on_progress: ProgressFn, on_event: EventFn
    ) -> WorkflowResult:
        entries = parse_file(file_content, root=_host_root_for_content_type(content_type))
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

        tmdb = TMDBService()
        llm = create_llm_service(settings)

        orchestrator = PathImportOrchestrator(
            session,
            tmdb,
            content_type=content_type,
            dry_run=dry_run,
            llm=llm,
            on_event=on_event,
            mode=mode,
        )
        import_result = await orchestrator.run(entries, on_progress=on_progress)

        summary: dict[str, object] = {
            "shows_processed": import_result.shows_processed,
            "shows_created": import_result.shows_created,
            "shows_found": import_result.shows_found,
            "shows_not_found": import_result.shows_not_found,
            "episodes_tracked": import_result.episodes_tracked,
            "episodes_unmatched": import_result.episodes_unmatched,
            "episodes_already_tracked": import_result.episodes_already_tracked,
            "show_results": [
                {
                    "show_dir": r.show_dir,
                    "tmdb_id": r.tmdb_id,
                    "tmdb_title": r.tmdb_title,
                    "action": r.action,
                    "episodes_tracked": r.episodes_tracked,
                    "episodes_unmatched": r.episodes_unmatched,
                    "episodes_already_tracked": r.episodes_already_tracked,
                    "unmatched_paths": r.unmatched_paths,
                    "already_tracked_paths": r.already_tracked_paths,
                }
                for r in import_result.show_results
            ],
            "dry_run": dry_run,
            "mode": import_result.mode,
        }

        if import_result.mode == "shows_only":
            done_message = (
                f"Done — {import_result.shows_created} created, "
                f"{import_result.shows_found} found (episode matching skipped)"
            )
        else:
            done_message = (
                f"Done — {import_result.shows_created} created, "
                f"{import_result.shows_found} found, "
                f"{import_result.episodes_tracked} episodes tracked"
            )

        return WorkflowResult(
            progress_current=import_result.shows_processed,
            progress_total=import_result.shows_processed,
            message=done_message,
            result_summary=summary,
        )

    return await run_task_workflow(
        celery_task_id,
        "import",
        _work,
        progress_total=0,
        dry_run=dry_run,
        running_message="Parsing file…",
    )

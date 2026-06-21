"""API routes for batch imports (path text file and database JSON)."""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.task import BackgroundTask
from jidou.schemas.task_schema import TaskRead
from jidou.services.progress import create_task_record

router = APIRouter(prefix="/import", tags=["import"])

_CONTENT_TYPES = {"anime", "tv", "movie"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB — more than enough for any path list
_MAX_DB_BYTES = 100 * 1024 * 1024  # 100 MB for database exports


@router.post("/text", response_model=TaskRead)
async def import_text(
    file: UploadFile,
    content_type: str = Form(default="anime"),
    dry_run: bool = Form(default=False),
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Upload a text file of episode paths and import them as a background task.

    Each line should be an absolute path to an episode file — either
    Windows-style (``Z:\\anime tv\\Dorohedoro\\Season 01\\ep.mkv``) or
    POSIX-style (``/mnt/media/anime/Dorohedoro/Season 01/ep.mkv``).
    Format is detected automatically per line.

    The task:
    1. Parses every line into a show directory, season, and episode number.
    2. Finds or creates each show by searching TMDB (handles Japanese names).
    3. Marks matched episode rows ``file_tracked = True``.

    Progress is streamed over WebSocket (``/ws``).  The completed task record
    includes a ``result_summary`` with per-show counts.

    Args:
        file: Plain-text file with one absolute path per line.
        content_type: Content type assigned to newly created shows
            (``anime``, ``tv``, or ``movie``).
        dry_run: Parse and match without writing to the database.
        db_session: Injected async database session.

    Returns:
        :class:`~jidou.models.task.BackgroundTask` row that can be polled or
        tracked over WebSocket.

    Raises:
        HTTPException: 400 if ``content_type`` is not recognised.
        HTTPException: 422 if the uploaded file exceeds the size limit.
    """
    if content_type not in _CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"content_type must be one of: {', '.join(sorted(_CONTENT_TYPES))}",
        )

    raw = await file.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=422, detail="File too large (limit: 10 MB)")

    # Decode; tolerate Windows / Unix line endings and BOM.
    try:
        file_content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        file_content = raw.decode("latin-1")

    # Delayed import to avoid circular references with the Celery app.
    from jidou.workers.import_tasks import path_import_task

    task_id = str(uuid.uuid4())
    new_task = await create_task_record(
        db_session,
        task_id,
        "import",
        dry_run=dry_run,
    )

    try:
        path_import_task.apply_async(
            args=[file_content, content_type, dry_run],
            task_id=task_id,
        )
    except Exception as exc:
        from datetime import UTC, datetime

        from jidou.models.task import TaskStatus

        new_task.status = TaskStatus.FAILED.value
        new_task.progress_message = f"Failed to enqueue task: {exc}"
        new_task.completed_at = datetime.now(UTC)
        await db_session.commit()
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc

    return new_task


@router.post("/database", response_model=TaskRead)
async def import_database(
    file: UploadFile,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Upload a Jidou database backup JSON and restore it as a background task.

    Accepts a JSON file produced by ``GET /api/export/database``.  Shows and
    episodes are upserted by their TMDB IDs; watchlist entries are upserted by
    ``show_id``.  Existing records that match are updated; ``local_path`` on
    shows is preserved when the backup value is absent.

    Args:
        file: JSON backup file exported by ``GET /api/export/database``.
        db_session: Injected async database session.

    Returns:
        :class:`~jidou.models.task.BackgroundTask` row for tracking.

    Raises:
        HTTPException: 422 if the uploaded file exceeds the size limit or is
            not valid JSON.
    """
    raw = await file.read(_MAX_DB_BYTES + 1)
    if len(raw) > _MAX_DB_BYTES:
        raise HTTPException(status_code=422, detail="File too large (limit: 100 MB)")

    try:
        file_content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        file_content = raw.decode("latin-1")

    import json

    try:
        json.loads(file_content)  # validate JSON before queuing
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc

    from jidou.workers.db_import_tasks import db_import_task

    task_id = str(uuid.uuid4())
    new_task = await create_task_record(
        db_session,
        task_id,
        "db_import",
        dry_run=False,
    )

    try:
        db_import_task.apply_async(args=[file_content], task_id=task_id)
    except Exception as exc:
        from datetime import UTC, datetime

        from jidou.models.task import TaskStatus

        new_task.status = TaskStatus.FAILED.value
        new_task.progress_message = f"Failed to enqueue task: {exc}"
        new_task.completed_at = datetime.now(UTC)
        await db_session.commit()
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc

    return new_task

"""API routes for the YaRSS2 config: download, diff, snapshots, import and publish."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.api.lookups import one_or_404
from jidou.config import settings
from jidou.database import get_session
from jidou.models.rss import RssConfigSnapshot
from jidou.models.task import BackgroundTask
from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator
from jidou.schemas.rss_schema import (
    RssConfigDiff,
)
from jidou.schemas.task_schema import TaskRead
from jidou.services.rss_config import (
    diff_rss_config,
    parse_rss_config,
)
from jidou.services.task_dispatch import CeleryTaskRef, TaskDispatchError, enqueue_celery_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss", tags=["rss"])


# ---------------------------------------------------------------------------
# Download (compose current DB state as a YaRSS2 config file)
# ---------------------------------------------------------------------------


@router.get("/download")
async def download_config(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> Response:
    """Compose and download the current DB state as a YaRSS2 config file.

    Uses the latest stored snapshot for the header and non-managed sections,
    then overlays the current DB feeds and enabled subscriptions via
    :meth:`RssPublishOrchestrator.compose_config` — the same composition
    logic ``run()`` uses to build what it actually uploads, so this
    preview can't drift from real publish behavior. Does not upload to the
    remote server; ``upload=False`` computes subscription keys without
    persisting them.

    Args:
        db_session: DB session (injected).

    Returns:
        ``application/octet-stream`` response with ``yarss2.conf`` filename.

    Raises:
        HTTPException: 404 if no snapshot exists (run an import first).
        HTTPException: 500 if the latest snapshot cannot be parsed.
    """
    snapshot_stmt = select(RssConfigSnapshot).order_by(RssConfigSnapshot.created_at.desc()).limit(1)
    snapshot = await one_or_404(
        db_session, snapshot_stmt, detail="No config snapshot found — run an import first"
    )

    try:
        header, old_body = parse_rss_config(snapshot.raw_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse latest snapshot: {exc}"
        ) from exc

    orchestrator = RssPublishOrchestrator(db_session, None, "", dry_run=True)
    composed, _result = await orchestrator.compose_config(header, old_body, upload=False)

    return Response(
        content=composed.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="yarss2.conf"'},
    )


@router.get("/diff", response_model=RssConfigDiff)
async def diff_config(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RssConfigDiff:
    """Diff the current DB-composed config against the last stored snapshot.

    Answers "what would change if I published right now?" without touching
    the remote server. Composes the current DB state the same way
    :meth:`RssPublishOrchestrator.compose_config` (and therefore a real
    publish) would, then diffs it against the most recent snapshot — the
    last config Jidou actually saw on the remote server, whether from an
    explicit import, the pre-publish reconciliation step of a prior publish,
    or (most commonly) the ``post_publish`` snapshot :meth:`RssPublishOrchestrator.run`
    stores of exactly what it just uploaded.

    Args:
        db_session: DB session (injected).

    Returns:
        :class:`RssConfigDiff` with unified diff lines and a reference to
        the snapshot the diff was taken against.

    Raises:
        HTTPException: 404 if no snapshot exists (run an import first).
        HTTPException: 500 if the latest snapshot cannot be parsed.
    """
    snapshot_stmt = select(RssConfigSnapshot).order_by(RssConfigSnapshot.created_at.desc()).limit(1)
    snapshot = await one_or_404(
        db_session, snapshot_stmt, detail="No config snapshot found — run an import first"
    )

    try:
        header, old_body = parse_rss_config(snapshot.raw_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse latest snapshot: {exc}"
        ) from exc

    orchestrator = RssPublishOrchestrator(db_session, None, "", dry_run=True)
    composed, _result = await orchestrator.compose_config(header, old_body, upload=False)
    new_header, new_body = parse_rss_config(composed)

    diff_lines = diff_rss_config(header, old_body, new_header, new_body)

    return RssConfigDiff(
        snapshot_id=snapshot.id,
        snapshot_type=snapshot.snapshot_type,
        snapshot_created_at=snapshot.created_at,
        has_changes=bool(diff_lines),
        diff=diff_lines,
    )


# ---------------------------------------------------------------------------
# Snapshots (read-only)
# ---------------------------------------------------------------------------


@router.get("/snapshots", response_model=list[dict[str, object]])
async def list_snapshots(
    limit: int = 20,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[dict[str, object]]:
    """Return recent RSS config snapshots (most recent first).

    Args:
        limit: Maximum records to return (default 20).
        db_session: DB session (injected).

    Returns:
        List of snapshot summaries (id, snapshot_type, created_at, content length).
    """
    stmt = (
        select(
            RssConfigSnapshot.id,
            RssConfigSnapshot.snapshot_type,
            RssConfigSnapshot.created_at,
            func.length(RssConfigSnapshot.raw_content).label("content_length"),
        )
        .order_by(RssConfigSnapshot.created_at.desc())
        .limit(limit)
    )
    rows = (await db_session.execute(stmt)).all()
    return [
        {
            "id": row.id,
            "snapshot_type": row.snapshot_type,
            "created_at": row.created_at,
            "content_length": row.content_length,
        }
        for row in rows
    ]


@router.get("/snapshots/{snapshot_id}", response_model=dict[str, object])
async def get_snapshot(
    snapshot_id: int,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    """Return a single RSS config snapshot including its full raw content.

    The listing endpoint omits raw_content; use this to retrieve the actual
    config text for a specific import or pre-publish snapshot.

    Args:
        snapshot_id: Database primary key.
        db_session: DB session (injected).

    Returns:
        Snapshot record including raw_content.

    Raises:
        HTTPException: 404 if the snapshot is not found.
    """
    stmt = select(RssConfigSnapshot).where(RssConfigSnapshot.id == snapshot_id)
    snapshot = (await db_session.execute(stmt)).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {
        "id": snapshot.id,
        "snapshot_type": snapshot.snapshot_type,
        "created_at": snapshot.created_at,
        "raw_content": snapshot.raw_content,
    }


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


@router.post("/import", response_model=TaskRead, status_code=202)
async def trigger_rss_import(
    dry_run: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Download the remote YaRSS2 config and sync it into the database.

    Requires ``RSS_CONFIG_REMOTE_PATH`` to be configured.  Progress is
    streamed over WebSocket (``/ws``) using the returned task ID.

    Args:
        dry_run: Parse and reconcile without writing to the database.
        db_session: DB session (injected).

    Returns:
        Background task record for polling or WebSocket tracking.

    Raises:
        HTTPException: 422 if ``RSS_CONFIG_REMOTE_PATH`` is not configured.
        HTTPException: 503 if the Celery broker is unreachable.
    """
    if not settings.rss_config_remote_path:
        raise HTTPException(
            status_code=422,
            detail="RSS_CONFIG_REMOTE_PATH is not configured.",
        )

    try:
        return await enqueue_celery_task(
            db_session,
            "rss_import",
            CeleryTaskRef("jidou.workers.rss_tasks", "rss_import_task"),
            args=[dry_run],
            dry_run=dry_run,
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc


@router.post("/publish", response_model=TaskRead, status_code=202)
async def trigger_rss_publish(
    dry_run: bool = False,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> BackgroundTask:
    """Compose and upload the Jidou DB state back to the remote YaRSS2 config.

    Requires ``RSS_CONFIG_REMOTE_PATH`` to be configured.  Backs up the current
    remote file, reconciles out-of-band changes, then uploads the composed config.
    Progress is streamed over WebSocket (``/ws``) using the returned task ID.

    Args:
        dry_run: Plan the publish without uploading to the remote server.
        db_session: DB session (injected).

    Returns:
        Background task record for polling or WebSocket tracking.

    Raises:
        HTTPException: 422 if ``RSS_CONFIG_REMOTE_PATH`` is not configured.
        HTTPException: 503 if the Celery broker is unreachable.
    """
    if not settings.rss_config_remote_path:
        raise HTTPException(
            status_code=422,
            detail="RSS_CONFIG_REMOTE_PATH is not configured.",
        )

    try:
        return await enqueue_celery_task(
            db_session,
            "rss_publish",
            CeleryTaskRef("jidou.workers.rss_tasks", "rss_publish_task"),
            args=[dry_run],
            dry_run=dry_run,
        )
    except TaskDispatchError as exc:
        raise HTTPException(status_code=503, detail="Task broker unavailable") from exc

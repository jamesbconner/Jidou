"""API routes for database exports."""

import json
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry

router = APIRouter(prefix="/export", tags=["export"])

_EXPORT_VERSION = "1"


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Serialize a SQLAlchemy mapped instance to a plain dict.

    Converts ``date`` and ``datetime`` values to ISO-format strings so the
    result is JSON-safe.  Uses the mapper's column attribute list rather than
    ``__dict__`` to avoid including SQLAlchemy internal state keys.

    Args:
        row: A mapped SQLAlchemy model instance.

    Returns:
        Dict of column name → JSON-safe Python value.
    """
    result: dict[str, Any] = {}
    for attr in inspect(row).mapper.column_attrs:
        val = getattr(row, attr.key)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        result[attr.key] = val
    return result


@router.get("/database")
async def export_database(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> StreamingResponse:
    """Export all application data as a downloadable JSON backup file.

    Serializes all :class:`~jidou.models.show.Show`,
    :class:`~jidou.models.episode.Episode`, and
    :class:`~jidou.models.watchlist.WatchlistEntry` rows to JSON.
    The resulting file can be restored via ``POST /api/import/database``.

    Downloaded files are intentionally excluded — they can be re-discovered
    via an SFTP scan + match task.

    Args:
        db_session: Injected async database session.

    Returns:
        Streaming JSON file response with ``Content-Disposition: attachment``.
    """
    shows = (await db_session.execute(select(Show).order_by(Show.id))).scalars().all()
    episodes = (await db_session.execute(select(Episode).order_by(Episode.id))).scalars().all()
    watchlist = (
        (await db_session.execute(select(WatchlistEntry).order_by(WatchlistEntry.id)))
        .scalars()
        .all()
    )

    payload: dict[str, Any] = {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "shows": [_row_to_dict(s) for s in shows],
        "episodes": [_row_to_dict(e) for e in episodes],
        "watchlist": [_row_to_dict(w) for w in watchlist],
    }

    filename = f"jidou-backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    content = json.dumps(payload, default=str)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

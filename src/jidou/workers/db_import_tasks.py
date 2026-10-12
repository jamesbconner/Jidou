"""Celery task for restoring a Jidou database backup."""

import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from celery import shared_task
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.models.show import Show, show_columns
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.services.progress import check_task_cancelled
from jidou.workers._harness import (
    EventFn,
    ProgressFn,
    SetTotalFn,
    WorkflowResult,
    run_harnessed,
    run_task_workflow,
)

logger = logging.getLogger(__name__)

# Columns intentionally left out of restore: primary keys and server-managed
# timestamps that should reflect the moment of import, not the backup's.
_SHOW_EXCLUDED_COLUMNS = frozenset({"id", "created_at", "updated_at"})
_EPISODE_EXCLUDED_COLUMNS = frozenset({"id", "created_at", "updated_at"})


def _parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse an ISO-format datetime string from a backup row, or None if absent/invalid."""
    if not raw:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(str(raw))
    return None


def _parse_iso_date(raw: Any) -> date | None:
    """Parse an ISO-format date string from a backup row, or None if absent/invalid."""
    if not raw:
        return None
    with contextlib.suppress(ValueError):
        return date.fromisoformat(str(raw))
    return None


@dataclass(frozen=True)
class _Column:
    """How one model column is read from a backup row.

    Attributes:
        name: Model attribute name, which is also the backup-row key.
        default: Value used when building a new row and the key is absent.
        convert: Optional converter applied to the backup value when building.
        required: When true the key must be present to build (``KeyError`` otherwise).
    """

    name: str
    default: object = None
    convert: Callable[[Any], object] | None = None
    required: bool = False

    def build_value(self, row: dict[str, Any]) -> object:
        """Return the value to construct a new model with, read from a backup ``row``.

        Args:
            row: One backup row.

        Returns:
            The (possibly converted) value for this column.

        Raises:
            KeyError: If the column is required and absent from ``row``.
        """
        value = row[self.name] if self.required else row.get(self.name, self.default)
        return self.convert(value) if self.convert is not None else value


# Build-time defaults and required keys for Show; every other column defaults to None.
_SHOW_DEFAULTS: dict[str, object] = {
    "media_type": "tv",
    "vote_count": 0,
    "cached": False,
    "track_missing_episodes": True,
}
_SHOW_REQUIRED = frozenset({"tmdb_id", "title"})

# Columns _build_show/_update_show populate from a backup row. Derived from the
# model's own provenance tags so a new Show column is picked up automatically
# (``show_columns`` raises for an untagged one); of the "key" columns only
# ``tmdb_id`` is restored. Sorted so constructor order is deterministic.
_SHOW_COLUMNS: tuple[_Column, ...] = tuple(
    _Column(name, default=_SHOW_DEFAULTS.get(name), required=name in _SHOW_REQUIRED)
    for name in sorted(show_columns("tmdb", "user", "derived") | {"tmdb_id"})
)

# Never touched on update: tmdb_id is the upsert key and cached is local state.
# local_path has its own preserve-if-absent rule in ``_update_show``.
_SHOW_INSERT_ONLY = frozenset({"tmdb_id", "cached"})

# Columns _build_episode/_update_episode populate from a backup row.
_EPISODE_COLUMNS: tuple[_Column, ...] = (
    _Column("show_id", required=True),
    _Column("tmdb_id", required=True),
    _Column("season_number", required=True),
    _Column("episode_number", required=True),
    _Column("name", default=""),
    _Column("overview"),
    _Column("air_date", convert=_parse_iso_date),
    _Column("runtime"),
    _Column("absolute_episode_number"),
    _Column("episode_type"),
    _Column("still_path"),
    _Column("file_tracked", default=False),
    _Column("file_tracked_at", convert=_parse_iso_datetime),
    _Column("tracked_filename"),
    _Column("tracked_source"),
    _Column("watched", default=False),
    _Column("watched_at", convert=_parse_iso_datetime),
)

# Episode columns with bespoke update rules (see ``_update_episode``): the identity
# columns are never rewritten and the date/time columns ignore malformed input.
_EPISODE_UPDATE_SPECIAL = frozenset(
    {"show_id", "tmdb_id", "air_date", "file_tracked_at", "watched_at"}
)


def check_restore_field_coverage() -> dict[str, set[str]]:
    """Return any Show/Episode model columns not handled or explicitly excluded by restore.

    Compares each model's live mapper column list against the ``_SHOW_COLUMNS`` and
    ``_EPISODE_COLUMNS`` tables that ``_build_*``/``_update_*`` populate from, so a
    column added to a model without a matching restore-side change is caught by a
    test instead of silently being dropped on every future backup restore.

    Returns:
        Mapping of model name to the set of unaccounted-for column names;
        both sets are empty when restore covers every column.
    """
    show_cols = {attr.key for attr in inspect(Show).column_attrs}
    episode_cols = {attr.key for attr in inspect(Episode).column_attrs}
    return {
        "Show": show_cols - {c.name for c in _SHOW_COLUMNS} - _SHOW_EXCLUDED_COLUMNS,
        "Episode": episode_cols - {c.name for c in _EPISODE_COLUMNS} - _EPISODE_EXCLUDED_COLUMNS,
    }


@shared_task(bind=True)  # type: ignore[untyped-decorator]
def db_import_task(  # type: ignore[no-untyped-def]
    self,
    file_content: str,
) -> str:
    """Restore a Jidou database backup from a JSON export file.

    Shows and episodes are upserted by ``tmdb_id``; watchlist entries are
    upserted by ``show_id``.  ``local_path`` on shows is preserved when the
    backup value is absent.

    Args:
        self: Celery request context.
        file_content: JSON string produced by ``GET /api/export/database``.

    Returns:
        The Celery task ID.
    """
    return run_harnessed(self.request.id, lambda: _db_import(self.request.id, file_content))


@dataclass
class _RestoreCounts:
    """Created/updated tallies for one restored section."""

    created: int = 0
    updated: int = 0


class _Progress:
    """Running row counter shared by the three restore sections.

    Attributes:
        current: Rows processed so far across all sections.
        total: Rows in the whole backup.
    """

    def __init__(self, total: int, on_progress: ProgressFn) -> None:
        self.current = 0
        self.total = total
        self._on_progress = on_progress

    def count(self) -> None:
        """Count a row without reporting it (skipped rows, and every watchlist row)."""
        self.current += 1

    async def advance(self, message: str) -> None:
        """Count a restored row and report progress immediately."""
        self.current += 1
        await self._on_progress(self.current, self.total, message)

    async def advance_every(self, interval: int, label: str) -> None:
        """Count a restored row; report only when the running total hits ``interval``."""
        self.current += 1
        if self.current % interval == 0:
            await self._on_progress(self.current, self.total, f"{label}: {self.current}")


async def _db_import(celery_task_id: str, file_content: str) -> str:
    """Async implementation of the database import task."""

    async def _work(
        session: AsyncSession,
        on_progress: ProgressFn,
        on_event: EventFn,
        set_total: SetTotalFn,
    ) -> WorkflowResult:
        data: dict[str, Any] = json.loads(file_content)
        shows_data: list[dict[str, Any]] = data.get("shows", [])
        episodes_data: list[dict[str, Any]] = data.get("episodes", [])
        watchlist_data: list[dict[str, Any]] = data.get("watchlist", [])

        total = len(shows_data) + len(episodes_data) + len(watchlist_data)
        await set_total(
            total,
            f"Found {len(shows_data)} shows, "
            f"{len(episodes_data)} episodes, "
            f"{len(watchlist_data)} watchlist entries",
        )

        progress = _Progress(total, on_progress)
        shows, show_id_map = await _restore_shows(session, celery_task_id, shows_data, progress)
        episodes = await _restore_episodes(
            session, celery_task_id, episodes_data, show_id_map, progress
        )
        watchlist = await _restore_watchlist(
            session, celery_task_id, watchlist_data, show_id_map, progress
        )

        summary: dict[str, object] = {
            "shows_created": shows.created,
            "shows_updated": shows.updated,
            "episodes_created": episodes.created,
            "episodes_updated": episodes.updated,
            "watchlist_created": watchlist.created,
            "watchlist_updated": watchlist.updated,
        }

        return WorkflowResult(
            progress_current=total,
            progress_total=total,
            message=(
                f"Done — {shows.created} shows created, {shows.updated} updated; "
                f"{episodes.created} episodes created, {episodes.updated} updated"
            ),
            result_summary=summary,
        )

    return await run_task_workflow(
        celery_task_id,
        "db_import",
        _work,
        dry_run=False,
        running_message="Parsing backup file…",
    )


# ---------------------------------------------------------------------------
# Restore sections
# ---------------------------------------------------------------------------


def _remap_show_id(row: dict[str, Any], show_id_map: dict[int, int]) -> tuple[int | None, Any]:
    """Translate a row's backup ``show_id`` to the restored database id.

    Args:
        row: An episode or watchlist backup row.
        show_id_map: Backup primary key -> restored id.

    Returns:
        ``(actual_show_id, backup_show_id)``; ``actual_show_id`` is None when the
        row has no ``show_id`` or the show was not restored.
    """
    backup_show_id = row.get("show_id")
    actual = show_id_map.get(backup_show_id) if backup_show_id is not None else None
    return actual, backup_show_id


async def _upsert_show(session: AsyncSession, row: dict[str, Any]) -> tuple[Show, bool]:
    """Create or update the Show for a validated backup row.

    Args:
        session: Active database session.
        row: Backup row with a non-null ``tmdb_id`` and a non-empty ``title``.

    Returns:
        ``(show, created)`` with ``show.id`` assigned in both cases.
    """
    existing = (
        await session.execute(select(Show).where(Show.tmdb_id == row["tmdb_id"]))
    ).scalar_one_or_none()
    if existing is not None:
        _update_show(existing, row)
        return existing, False
    show = _build_show(row)
    session.add(show)
    # Flush immediately so the ORM assigns show.id before the caller records it
    # in the remap table.
    await session.flush()
    return show, True


async def _restore_shows(
    session: AsyncSession,
    task_id: str,
    rows: list[dict[str, Any]],
    progress: _Progress,
) -> tuple[_RestoreCounts, dict[int, int]]:
    """Upsert shows by ``tmdb_id`` and commit.

    Args:
        session: Active database session.
        task_id: Celery task ID, polled for cancellation before every row.
        rows: Backup show rows.
        progress: Shared row counter; reports after every restored row.

    Returns:
        The created/updated counts and a map of backup show id -> restored id, so
        episodes and watchlist rows link to the right show even when auto-increment
        values differ between the backup and the restored database.
    """
    counts = _RestoreCounts()
    show_id_map: dict[int, int] = {}
    for row in rows:
        await check_task_cancelled(session, task_id)
        tmdb_id = row.get("tmdb_id")
        if tmdb_id is None:
            logger.warning("Skipping show row with missing tmdb_id: %r", row)
            progress.count()
            continue
        if not row.get("title"):
            logger.warning("Skipping show tmdb_id=%s with missing title", tmdb_id)
            progress.count()
            continue

        show, created = await _upsert_show(session, row)
        backup_show_id: int | None = row.get("id")
        if backup_show_id is not None:
            show_id_map[backup_show_id] = show.id
        if created:
            counts.created += 1
        else:
            counts.updated += 1
        await progress.advance(f"Shows: {tmdb_id}")

    await session.commit()
    return counts, show_id_map


async def _restore_episodes(
    session: AsyncSession,
    task_id: str,
    rows: list[dict[str, Any]],
    show_id_map: dict[int, int],
    progress: _Progress,
) -> _RestoreCounts:
    """Upsert episodes by ``tmdb_id`` and commit.

    Args:
        session: Active database session.
        task_id: Celery task ID, polled for cancellation before every row.
        rows: Backup episode rows.
        show_id_map: Backup show id -> restored show id.
        progress: Shared row counter; reports every 100th row.

    Returns:
        The created/updated counts.
    """
    counts = _RestoreCounts()
    for row in rows:
        await check_task_cancelled(session, task_id)
        ep_tmdb_id = row.get("tmdb_id")
        if ep_tmdb_id is None:
            logger.warning("Skipping episode row with missing tmdb_id")
            progress.count()
            continue

        actual_show_id, backup_show_id = _remap_show_id(row, show_id_map)
        if actual_show_id is None:
            logger.warning(
                "Skipping episode tmdb_id=%s: backup show_id=%s not in restore map",
                ep_tmdb_id,
                backup_show_id,
            )
            progress.count()
            continue

        existing = (
            await session.execute(select(Episode).where(Episode.tmdb_id == ep_tmdb_id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(_build_episode({**row, "show_id": actual_show_id}))
            counts.created += 1
        else:
            _update_episode(existing, row)
            counts.updated += 1
        await progress.advance_every(100, "Episodes")

    await session.commit()
    return counts


async def _restore_watchlist(
    session: AsyncSession,
    task_id: str,
    rows: list[dict[str, Any]],
    show_id_map: dict[int, int],
    progress: _Progress,
) -> _RestoreCounts:
    """Upsert watchlist entries by ``show_id`` and commit.

    Args:
        session: Active database session.
        task_id: Celery task ID, polled for cancellation before every row.
        rows: Backup watchlist rows.
        show_id_map: Backup show id -> restored show id.
        progress: Shared row counter; this section never reports progress.

    Returns:
        The created/updated counts.
    """
    counts = _RestoreCounts()
    for row in rows:
        await check_task_cancelled(session, task_id)
        actual_show_id, backup_show_id = _remap_show_id(row, show_id_map)
        if actual_show_id is None:
            logger.warning(
                "Skipping watchlist entry: backup show_id=%s not in restore map",
                backup_show_id,
            )
            progress.count()
            continue

        existing = (
            await session.execute(
                select(WatchlistEntry).where(WatchlistEntry.show_id == actual_show_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                WatchlistEntry(
                    show_id=actual_show_id,
                    status=WatchlistStatus(row.get("status", "planned")),
                    notes=row.get("notes"),
                    position=row.get("position", 0),
                )
            )
            counts.created += 1
        else:
            existing.status = WatchlistStatus(row.get("status", existing.status))
            existing.notes = row.get("notes", existing.notes)
            existing.position = row.get("position", existing.position)
            counts.updated += 1
        progress.count()  # the watchlist section never reports progress

    await session.commit()
    return counts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_show(row: dict[str, Any]) -> Show:
    """Construct a new Show from a backup row dict."""
    return Show(**{col.name: col.build_value(row) for col in _SHOW_COLUMNS})


def _update_show(show: Show, row: dict[str, Any]) -> None:
    """Update an existing Show from a backup row dict, preserving local_path."""
    for col in _SHOW_COLUMNS:
        if col.name in _SHOW_INSERT_ONLY or col.name == "local_path":
            continue
        setattr(show, col.name, row.get(col.name, getattr(show, col.name)))
    # Preserve live local_path if backup value is absent.
    backup_local_path = row.get("local_path")
    if backup_local_path is not None:
        show.local_path = backup_local_path


def _build_episode(row: dict[str, Any]) -> Episode:
    """Construct a new Episode from a backup row dict."""
    return Episode(**{col.name: col.build_value(row) for col in _EPISODE_COLUMNS})


def _update_episode(ep: Episode, row: dict[str, Any]) -> None:
    """Update an existing Episode from a backup row dict."""
    for col in _EPISODE_COLUMNS:
        if col.name not in _EPISODE_UPDATE_SPECIAL:
            setattr(ep, col.name, row.get(col.name, getattr(ep, col.name)))

    for name in ("file_tracked_at", "watched_at"):
        if name not in row:
            continue
        raw = row[name]
        if raw is None:
            # Explicit null is a legitimate signal that the timestamp was cleared.
            setattr(ep, name, None)
        else:
            parsed = _parse_iso_datetime(raw)
            # A malformed (non-null) value should not silently wipe a valid
            # existing timestamp -- leave it untouched, same as air_date.
            if parsed is not None:
                setattr(ep, name, parsed)

    parsed_air_date = _parse_iso_date(row.get("air_date"))
    if parsed_air_date is not None:
        ep.air_date = parsed_air_date

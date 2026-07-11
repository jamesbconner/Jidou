"""Celery task for restoring a Jidou database backup."""

import asyncio
import contextlib
import json
import logging
from datetime import date, datetime
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.models.task import TaskStatus
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus
from jidou.services.progress import (
    TaskCancelledError,
    check_task_cancelled,
    create_task_record,
    emit_progress,
    mark_task_timed_out,
    update_task_status,
)

logger = logging.getLogger(__name__)

# Columns intentionally left out of restore: primary keys and server-managed
# timestamps that should reflect the moment of import, not the backup's.
_SHOW_EXCLUDED_COLUMNS = frozenset({"id", "created_at", "updated_at"})
_EPISODE_EXCLUDED_COLUMNS = frozenset({"id", "created_at", "updated_at"})

# Columns _build_show/_update_show populate from a backup row.
_SHOW_HANDLED_COLUMNS = frozenset(
    {
        "tmdb_id",
        "title",
        "overview",
        "media_type",
        "poster_path",
        "backdrop_path",
        "vote_average",
        "vote_count",
        "release_date",
        "original_language",
        "cached",
        "content_type",
        "sys_name",
        "aliases",
        "aliases_sources",
        "genres",
        "origin_country",
        "last_air_date",
        "last_episode_to_air",
        "next_episode_to_air",
        "homepage",
        "external_ids",
        "episode_groups",
        "status",
        "in_production",
        "number_of_seasons",
        "number_of_episodes",
        "networks",
        "show_type",
        "runtime",
        "tagline",
        "local_path",
        "adult",
    }
)

# Columns _build_episode/_update_episode populate from a backup row.
_EPISODE_HANDLED_COLUMNS = frozenset(
    {
        "show_id",
        "tmdb_id",
        "season_number",
        "episode_number",
        "name",
        "overview",
        "air_date",
        "runtime",
        "absolute_episode_number",
        "episode_type",
        "still_path",
        "file_tracked",
        "file_tracked_at",
        "tracked_filename",
        "tracked_source",
    }
)


def check_restore_field_coverage() -> dict[str, set[str]]:
    """Return any Show/Episode model columns not handled or explicitly excluded by restore.

    Compares each model's live mapper column list against the field sets
    ``_build_show``/``_update_show`` and ``_build_episode``/``_update_episode``
    actually populate, so a column added to a model without a matching
    restore-side change is caught by a test instead of silently being dropped
    on every future backup restore.

    Returns:
        Mapping of model name to the set of unaccounted-for column names;
        both sets are empty when restore covers every column.
    """
    show_columns = {attr.key for attr in inspect(Show).column_attrs}
    episode_columns = {attr.key for attr in inspect(Episode).column_attrs}
    return {
        "Show": show_columns - _SHOW_HANDLED_COLUMNS - _SHOW_EXCLUDED_COLUMNS,
        "Episode": episode_columns - _EPISODE_HANDLED_COLUMNS - _EPISODE_EXCLUDED_COLUMNS,
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
    try:
        return asyncio.run(_db_import(self.request.id, file_content))
    except SoftTimeLimitExceeded:
        asyncio.run(mark_task_timed_out(self.request.id))
        raise


async def _db_import(celery_task_id: str, file_content: str) -> str:
    """Async implementation of the database import task."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as session:
            task = await create_task_record(
                session,
                celery_task_id,
                "db_import",
                progress_total=0,
                dry_run=False,
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
                progress_message="Parsing backup file…",
            )

            data: dict[str, Any] = json.loads(file_content)
            shows_data: list[dict[str, Any]] = data.get("shows", [])
            episodes_data: list[dict[str, Any]] = data.get("episodes", [])
            watchlist_data: list[dict[str, Any]] = data.get("watchlist", [])

            total = len(shows_data) + len(episodes_data) + len(watchlist_data)
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.RUNNING,
                progress_total=total,
                progress_message=(
                    f"Found {len(shows_data)} shows, "
                    f"{len(episodes_data)} episodes, "
                    f"{len(watchlist_data)} watchlist entries"
                ),
            )

            current = 0
            shows_created = shows_updated = 0
            episodes_created = episodes_updated = 0
            watchlist_created = watchlist_updated = 0

            # Maps backup primary-key → actual DB id so episodes and watchlist
            # rows can be linked to the correct show even when auto-increment
            # values differ between the backup and the restored database.
            show_id_map: dict[int, int] = {}

            # --- Shows ---
            for row in shows_data:
                await check_task_cancelled(session, celery_task_id)
                tmdb_id = row.get("tmdb_id")
                if tmdb_id is None:
                    logger.warning("Skipping show row with missing tmdb_id: %r", row)
                    current += 1
                    continue

                title = row.get("title")
                if not title:
                    logger.warning("Skipping show tmdb_id=%s with missing title", tmdb_id)
                    current += 1
                    continue

                backup_show_id: int | None = row.get("id")

                existing = (
                    await session.execute(select(Show).where(Show.tmdb_id == tmdb_id))
                ).scalar_one_or_none()

                if existing is None:
                    show = _build_show(row)
                    session.add(show)
                    # Flush immediately so the ORM assigns show.id before we
                    # continue building the remap table.
                    await session.flush()
                    if backup_show_id is not None:
                        show_id_map[backup_show_id] = show.id
                    shows_created += 1
                else:
                    _update_show(existing, row)
                    if backup_show_id is not None:
                        show_id_map[backup_show_id] = existing.id
                    shows_updated += 1

                current += 1
                await _emit_progress(session, celery_task_id, current, total, f"Shows: {tmdb_id}")

            await session.commit()

            # --- Episodes ---
            for row in episodes_data:
                await check_task_cancelled(session, celery_task_id)
                ep_tmdb_id = row.get("tmdb_id")
                if ep_tmdb_id is None:
                    logger.warning("Skipping episode row with missing tmdb_id")
                    current += 1
                    continue

                backup_show_id = row.get("show_id")
                actual_show_id = (
                    show_id_map.get(backup_show_id) if backup_show_id is not None else None
                )

                if actual_show_id is None:
                    logger.warning(
                        "Skipping episode tmdb_id=%s: backup show_id=%s not in restore map",
                        ep_tmdb_id,
                        backup_show_id,
                    )
                    current += 1
                    continue

                existing_ep = (
                    await session.execute(select(Episode).where(Episode.tmdb_id == ep_tmdb_id))
                ).scalar_one_or_none()

                if existing_ep is None:
                    ep = _build_episode({**row, "show_id": actual_show_id})
                    session.add(ep)
                    episodes_created += 1
                else:
                    _update_episode(existing_ep, row)
                    episodes_updated += 1

                current += 1
                if current % 100 == 0:
                    await _emit_progress(
                        session, celery_task_id, current, total, f"Episodes: {current}"
                    )

            await session.commit()

            # --- Watchlist ---
            for row in watchlist_data:
                await check_task_cancelled(session, celery_task_id)
                backup_show_id = row.get("show_id")
                actual_show_id = (
                    show_id_map.get(backup_show_id) if backup_show_id is not None else None
                )

                if actual_show_id is None:
                    logger.warning(
                        "Skipping watchlist entry: backup show_id=%s not in restore map",
                        backup_show_id,
                    )
                    current += 1
                    continue

                existing_wl = (
                    await session.execute(
                        select(WatchlistEntry).where(WatchlistEntry.show_id == actual_show_id)
                    )
                ).scalar_one_or_none()

                if existing_wl is None:
                    wl = WatchlistEntry(
                        show_id=actual_show_id,
                        status=WatchlistStatus(row.get("status", "planned")),
                        notes=row.get("notes"),
                        position=row.get("position", 0),
                    )
                    session.add(wl)
                    watchlist_created += 1
                else:
                    existing_wl.status = WatchlistStatus(row.get("status", existing_wl.status))
                    existing_wl.notes = row.get("notes", existing_wl.notes)
                    existing_wl.position = row.get("position", existing_wl.position)
                    watchlist_updated += 1

                current += 1

            await session.commit()

            summary: dict[str, object] = {
                "shows_created": shows_created,
                "shows_updated": shows_updated,
                "episodes_created": episodes_created,
                "episodes_updated": episodes_updated,
                "watchlist_created": watchlist_created,
                "watchlist_updated": watchlist_updated,
            }

            final_task = await update_task_status(
                session,
                celery_task_id,
                TaskStatus.COMPLETED,
                progress_current=total,
                progress_total=total,
                progress_message=(
                    f"Done — {shows_created} shows created, {shows_updated} updated; "
                    f"{episodes_created} episodes created, {episodes_updated} updated"
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
        logger.info("DB import task %s was cancelled", celery_task_id)
    except Exception:
        logger.exception("DB import task %s failed", celery_task_id)
        async with session_factory() as session:
            await update_task_status(
                session,
                celery_task_id,
                TaskStatus.FAILED,
                progress_message="Database import failed — see logs",
            )
        await emit_progress(
            {
                "celery_task_id": celery_task_id,
                "type": "error",
                "data": {"error": "Database import failed"},
            }
        )
        raise
    finally:
        await engine.dispose()

    return celery_task_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _emit_progress(
    session: AsyncSession,
    celery_task_id: str,
    current: int,
    total: int,
    message: str,
) -> None:
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


def _build_show(row: dict[str, Any]) -> Show:
    """Construct a new Show from a backup row dict."""
    return Show(
        tmdb_id=row["tmdb_id"],
        title=row["title"],
        overview=row.get("overview"),
        media_type=row.get("media_type", "tv"),
        poster_path=row.get("poster_path"),
        backdrop_path=row.get("backdrop_path"),
        vote_average=row.get("vote_average"),
        vote_count=row.get("vote_count", 0),
        release_date=row.get("release_date"),
        original_language=row.get("original_language"),
        cached=row.get("cached", False),
        content_type=row.get("content_type"),
        sys_name=row.get("sys_name"),
        aliases=row.get("aliases"),
        aliases_sources=row.get("aliases_sources"),
        genres=row.get("genres"),
        origin_country=row.get("origin_country"),
        last_air_date=row.get("last_air_date"),
        last_episode_to_air=row.get("last_episode_to_air"),
        next_episode_to_air=row.get("next_episode_to_air"),
        homepage=row.get("homepage"),
        external_ids=row.get("external_ids"),
        episode_groups=row.get("episode_groups"),
        status=row.get("status"),
        in_production=row.get("in_production"),
        number_of_seasons=row.get("number_of_seasons"),
        number_of_episodes=row.get("number_of_episodes"),
        networks=row.get("networks"),
        show_type=row.get("show_type"),
        runtime=row.get("runtime"),
        tagline=row.get("tagline"),
        local_path=row.get("local_path"),
        adult=row.get("adult"),
    )


def _update_show(show: Show, row: dict[str, Any]) -> None:
    """Update an existing Show from a backup row dict, preserving local_path."""
    show.title = row.get("title", show.title)
    show.overview = row.get("overview", show.overview)
    show.media_type = row.get("media_type", show.media_type)
    show.poster_path = row.get("poster_path", show.poster_path)
    show.backdrop_path = row.get("backdrop_path", show.backdrop_path)
    show.vote_average = row.get("vote_average", show.vote_average)
    show.vote_count = row.get("vote_count", show.vote_count)
    show.release_date = row.get("release_date", show.release_date)
    show.original_language = row.get("original_language", show.original_language)
    show.content_type = row.get("content_type", show.content_type)
    show.sys_name = row.get("sys_name", show.sys_name)
    show.aliases = row.get("aliases", show.aliases)
    show.aliases_sources = row.get("aliases_sources", show.aliases_sources)
    show.genres = row.get("genres", show.genres)
    show.origin_country = row.get("origin_country", show.origin_country)
    show.last_air_date = row.get("last_air_date", show.last_air_date)
    show.last_episode_to_air = row.get("last_episode_to_air", show.last_episode_to_air)
    show.next_episode_to_air = row.get("next_episode_to_air", show.next_episode_to_air)
    show.homepage = row.get("homepage", show.homepage)
    show.external_ids = row.get("external_ids", show.external_ids)
    show.episode_groups = row.get("episode_groups", show.episode_groups)
    show.status = row.get("status", show.status)
    show.in_production = row.get("in_production", show.in_production)
    show.number_of_seasons = row.get("number_of_seasons", show.number_of_seasons)
    show.number_of_episodes = row.get("number_of_episodes", show.number_of_episodes)
    show.networks = row.get("networks", show.networks)
    show.show_type = row.get("show_type", show.show_type)
    show.runtime = row.get("runtime", show.runtime)
    show.tagline = row.get("tagline", show.tagline)
    show.adult = row.get("adult", show.adult)
    # Preserve live local_path if backup value is absent.
    backup_local_path = row.get("local_path")
    if backup_local_path is not None:
        show.local_path = backup_local_path


def _parse_iso_datetime(raw: Any) -> datetime | None:
    """Parse an ISO-format datetime string from a backup row, or None if absent/invalid."""
    if not raw:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(str(raw))
    return None


def _build_episode(row: dict[str, Any]) -> Episode:
    """Construct a new Episode from a backup row dict."""
    air_date_raw = row.get("air_date")
    air_date: date | None = None
    if air_date_raw:
        with contextlib.suppress(ValueError):
            air_date = date.fromisoformat(str(air_date_raw))

    return Episode(
        show_id=row["show_id"],
        tmdb_id=row["tmdb_id"],
        season_number=row["season_number"],
        episode_number=row["episode_number"],
        name=row.get("name", ""),
        overview=row.get("overview"),
        air_date=air_date,
        runtime=row.get("runtime"),
        absolute_episode_number=row.get("absolute_episode_number"),
        episode_type=row.get("episode_type"),
        still_path=row.get("still_path"),
        file_tracked=row.get("file_tracked", False),
        file_tracked_at=_parse_iso_datetime(row.get("file_tracked_at")),
        tracked_filename=row.get("tracked_filename"),
        tracked_source=row.get("tracked_source"),
    )


def _update_episode(ep: Episode, row: dict[str, Any]) -> None:
    """Update an existing Episode from a backup row dict."""
    ep.season_number = row.get("season_number", ep.season_number)
    ep.episode_number = row.get("episode_number", ep.episode_number)
    ep.name = row.get("name", ep.name)
    ep.overview = row.get("overview", ep.overview)
    ep.runtime = row.get("runtime", ep.runtime)
    ep.absolute_episode_number = row.get("absolute_episode_number", ep.absolute_episode_number)
    ep.episode_type = row.get("episode_type", ep.episode_type)
    ep.still_path = row.get("still_path", ep.still_path)
    ep.file_tracked = row.get("file_tracked", ep.file_tracked)
    ep.tracked_filename = row.get("tracked_filename", ep.tracked_filename)
    ep.tracked_source = row.get("tracked_source", ep.tracked_source)

    if "file_tracked_at" in row:
        ep.file_tracked_at = _parse_iso_datetime(row.get("file_tracked_at"))

    air_date_raw = row.get("air_date")
    if air_date_raw:
        with contextlib.suppress(ValueError):
            ep.air_date = date.fromisoformat(str(air_date_raw))

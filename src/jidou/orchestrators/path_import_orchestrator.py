"""Orchestrator for importing episode file path lists into the database.

For each unique show directory found in the path list:

1. Searches the DB for an existing show by title or alias.
2. If not found, searches TMDB, creates the Show row, and syncs its episodes.
3. Matches each parsed file to an Episode row by season/episode number
   (or absolute episode number as a fallback).
4. Sets ``episode.file_tracked = True`` for every matched episode.

Japanese (romaji/kanji) directory names are passed directly to TMDB's
multi-language search, which resolves them to English titles.  The original
directory name is stored in ``show.aliases`` when it differs from the English
title so future lookups (parse orchestrator, manual search) hit the GIN index.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.services.path_parser import ParsedPathEntry, group_by_show
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize_sys_name(title: str) -> str:
    return _INVALID_FS_CHARS.sub("_", title).strip()


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ShowImportResult:
    """Import outcome for a single show directory.

    Attributes:
        show_dir: Directory name from the path file.
        tmdb_id: TMDB ID of the matched show, or None.
        tmdb_title: English title from TMDB, or None.
        action: One of ``"created"`` | ``"found"`` | ``"not_found"``.
        episodes_tracked: Number of episode rows marked ``file_tracked=True``.
        episodes_unmatched: Number of entries with no matching episode row.
    """

    show_dir: str
    tmdb_id: int | None = None
    tmdb_title: str | None = None
    action: str = "not_found"
    episodes_tracked: int = 0
    episodes_unmatched: int = 0


@dataclass
class PathImportResult:
    """Aggregate result of a full path-file import run.

    Attributes:
        shows_processed: Total unique show directories seen.
        shows_created: Shows newly created from TMDB.
        shows_found: Shows that already existed in the DB.
        shows_not_found: Shows that could not be matched to TMDB.
        episodes_tracked: Total episode rows marked ``file_tracked=True``.
        episodes_unmatched: Total entries with no matching episode row.
        show_results: Per-show breakdown.
    """

    shows_processed: int = 0
    shows_created: int = 0
    shows_found: int = 0
    shows_not_found: int = 0
    episodes_tracked: int = 0
    episodes_unmatched: int = 0
    show_results: list[ShowImportResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class PathImportOrchestrator:
    """Import a parsed list of episode file paths into the database.

    Args:
        session: Active async SQLAlchemy session.
        tmdb: Configured :class:`~jidou.services.tmdb.TMDBService` instance.
        content_type: Content type assigned to newly created shows
            (``"anime"``, ``"tv"``, or ``"movie"``).
        dry_run: When True, performs all lookups and matching but skips all
            database writes (no show creation, episode sync, or file_tracked
            updates).
    """

    def __init__(
        self,
        session: AsyncSession,
        tmdb: TMDBService,
        content_type: str = "anime",
        dry_run: bool = False,
    ) -> None:
        self.session = session
        self.tmdb = tmdb
        self.content_type = content_type
        self.dry_run = dry_run

    async def run(
        self,
        entries: list[ParsedPathEntry],
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> PathImportResult:
        """Run the full import workflow.

        Args:
            entries: Parsed entries from :func:`~jidou.services.path_parser.parse_file`.
            on_progress: Optional async callback ``(current, total, message)`` for
                progress reporting.

        Returns:
            :class:`PathImportResult` with aggregate and per-show counts.
        """
        result = PathImportResult()
        grouped = group_by_show(entries)
        result.shows_processed = len(grouped)
        total = len(grouped)

        for idx, (show_dir, show_entries) in enumerate(grouped.items(), 1):
            if on_progress:
                await on_progress(idx, total, f"Importing {show_dir}")

            show_result = await self._import_show(show_dir, show_entries)
            result.show_results.append(show_result)

            if show_result.action == "created":
                result.shows_created += 1
            elif show_result.action == "found":
                result.shows_found += 1
            else:
                result.shows_not_found += 1

            result.episodes_tracked += show_result.episodes_tracked
            result.episodes_unmatched += show_result.episodes_unmatched

        return result

    # ------------------------------------------------------------------
    # Per-show helpers
    # ------------------------------------------------------------------

    async def _import_show(
        self,
        show_dir: str,
        entries: list[ParsedPathEntry],
    ) -> ShowImportResult:
        """Import one show and mark its episode files as tracked.

        Args:
            show_dir: Show directory name (used as the primary search key).
            entries: All parsed file entries belonging to this show.

        Returns:
            :class:`ShowImportResult` for this show.
        """
        show_result = ShowImportResult(show_dir=show_dir)

        # Try the database first to avoid unnecessary TMDB calls.
        show = await self._db_find_show(show_dir)

        if show is None:
            show, action = await self._tmdb_create_show(show_dir)
            show_result.action = action
        else:
            show_result.action = "found"
            logger.info("Found existing show %r (id=%d) for dir %r", show.title, show.id, show_dir)
            # If episodes haven't been synced yet, do it now so file matching can proceed.
            if not self.dry_run:
                ep_count = await self.session.scalar(
                    select(func.count()).select_from(Episode).where(Episode.show_id == show.id)
                )
                if ep_count == 0:
                    logger.info(
                        "No episodes for show id=%d (%r); syncing from TMDB before matching",
                        show.id,
                        show.title,
                    )
                    try:
                        await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(show)
                    except Exception:
                        logger.exception("Episode sync failed for show id=%d", show.id)

        if show is None:
            logger.warning("Could not resolve show for directory %r", show_dir)
            show_result.episodes_unmatched = len(entries)
            return show_result

        show_result.tmdb_id = show.tmdb_id
        show_result.tmdb_title = show.title

        # Persist the show's root directory path if not already set.
        if not self.dry_run and show.local_path is None and entries:
            show.local_path = entries[0].show_root
            logger.debug("Set local_path=%r for show id=%d", show.local_path, show.id)

        # In dry-run mode, a newly "created" show has no database id and no
        # synced episodes yet, so _find_episode would query show_id=NULL and
        # return nothing.  Estimate from the parsed entries instead.
        if self.dry_run and show.id is None:
            for entry in entries:
                if entry.episode is not None:
                    show_result.episodes_tracked += 1
                else:
                    show_result.episodes_unmatched += 1
            return show_result

        # Match each file entry to an Episode row.
        for entry in entries:
            ep = await self._find_episode(show.id, entry)
            if ep is not None:
                if not ep.file_tracked:
                    if not self.dry_run:
                        ep.file_tracked = True
                        ep.file_tracked_at = datetime.now(UTC)
                    show_result.episodes_tracked += 1
                # Already tracked — count as matched but don't increment episodes_tracked.
            else:
                show_result.episodes_unmatched += 1
                logger.debug(
                    "No episode match: show=%r dir=%r season=%s episode=%s abs=%s path=%r",
                    show.title,
                    show_dir,
                    entry.season,
                    entry.episode,
                    entry.is_absolute,
                    entry.raw_path,
                )

        if not self.dry_run:
            await self.session.commit()
        return show_result

    async def _db_find_show(self, name: str) -> Show | None:
        """Look up a show in the database by title (ILIKE) or alias containment.

        Args:
            name: Show directory name to search for.

        Returns:
            Matching :class:`Show`, or None.
        """
        normalised = name.strip().lower()

        # GIN-indexed alias lookup — fastest path for re-imports.
        stmt = (
            select(Show)
            .where(Show.aliases.cast(JSONB).contains([normalised]))
            .order_by(Show.id)
            .limit(1)
        )
        show = (await self.session.execute(stmt)).scalars().first()
        if show:
            return show

        # Case-insensitive title fallback.
        escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = (
            select(Show)
            .where(Show.title.ilike(f"%{escaped}%", escape="\\"))
            .order_by(Show.id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _tmdb_create_show(self, show_dir: str) -> tuple[Show | None, str]:
        """Search TMDB for show_dir, create the Show row, and sync its episodes.

        TMDB's multi-language search handles both English and Japanese
        (romaji/kanji/kana) directory names transparently.  The original
        directory name is stored as an alias when it differs from the resolved
        English title so future lookups bypass TMDB.

        Args:
            show_dir: Show directory name to search for on TMDB.

        Returns:
            ``(show, action)`` where action is ``"created"`` or ``"not_found"``.
        """
        # Search TMDB.
        try:
            results = await self.tmdb.search(show_dir, media_type="tv")
        except Exception:
            logger.warning("TMDB search failed for %r", show_dir)
            return None, "not_found"

        candidates = [r for r in results.get("results", []) if r.get("media_type") in ("tv", None)]
        if not candidates:
            logger.warning("No TMDB results for directory %r", show_dir)
            return None, "not_found"

        # Exact name match wins; otherwise take the top relevance result.
        best = candidates[0]
        for c in candidates[:5]:
            if c.get("name", "").lower() == show_dir.lower():
                best = c
                break

        tmdb_id: int = best["id"]

        # Fetch full show details.
        try:
            data = await self.tmdb.get_details(tmdb_id, media_type="tv")
        except Exception:
            logger.warning("TMDB get_details failed for tmdb_id=%d", tmdb_id)
            return None, "not_found"

        title: str = data.get("name") or show_dir

        # Store the directory name as an alias when it differs from the English title.
        aliases: list[str] = []
        if show_dir.lower() != title.lower():
            aliases.append(show_dir.lower())

        # Supplemental TMDB calls are best-effort.
        ext_ids: dict[str, Any] = {}
        ep_groups: dict[str, Any] = {}
        try:
            ext_ids = await self.tmdb.get_external_ids(tmdb_id, media_type="tv")
        except Exception:
            logger.debug("get_external_ids failed for tmdb_id=%d", tmdb_id)
        try:
            ep_groups = await self.tmdb.get_episode_groups(tmdb_id)
        except Exception:
            logger.debug("get_episode_groups failed for tmdb_id=%d", tmdb_id)

        ep_runtimes: list[int] = data.get("episode_run_time") or []
        runtime: int | None = data.get("runtime") or (ep_runtimes[0] if ep_runtimes else None)

        show = Show(
            tmdb_id=tmdb_id,
            title=title,
            overview=data.get("overview"),
            media_type="tv",
            poster_path=data.get("poster_path"),
            backdrop_path=data.get("backdrop_path"),
            vote_average=data.get("vote_average"),
            vote_count=data.get("vote_count", 0),
            release_date=data.get("first_air_date"),
            original_language=data.get("original_language"),
            content_type=self.content_type,
            sys_name=_sanitize_sys_name(title),
            aliases=aliases,
            genres=data.get("genres") or [],
            origin_country=data.get("origin_country") or [],
            last_air_date=data.get("last_air_date"),
            last_episode_to_air=data.get("last_episode_to_air"),
            next_episode_to_air=data.get("next_episode_to_air"),
            homepage=data.get("homepage"),
            external_ids=ext_ids or {},
            episode_groups=list(ep_groups.get("results") or []),
            status=data.get("status"),
            in_production=data.get("in_production"),
            number_of_seasons=data.get("number_of_seasons"),
            number_of_episodes=data.get("number_of_episodes"),
            networks=data.get("networks") or [],
            show_type=data.get("type"),
            runtime=runtime,
            tagline=data.get("tagline"),
        )

        if self.dry_run:
            # Report what would be created without touching the database.
            logger.info("[dry-run] Would create show %r (tmdb_id=%d)", title, tmdb_id)
            return show, "created"

        try:
            self.session.add(show)
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            # Race condition: another request created this show concurrently.
            fallback = await self._db_find_show(title)
            if fallback:
                return fallback, "found"
            return None, "not_found"

        logger.info("Created show %r (tmdb_id=%d, id=%d)", title, tmdb_id, show.id)

        # Sync all episodes from TMDB so episode matching can proceed.
        try:
            await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(show)
        except Exception:
            logger.exception("Episode sync failed for %r (tmdb_id=%d)", title, tmdb_id)
            # Show row exists; proceed to episode matching with whatever was synced.

        return show, "created"

    async def _find_episode(
        self,
        show_id: int,
        entry: ParsedPathEntry,
    ) -> Episode | None:
        """Match a parsed path entry to an Episode row.

        Lookup priority:
        1. Season + episode (standard).
        2. Absolute episode number (``episode.absolute_episode_number``).
        3. Season 1, episode N as a last resort for absolute-numbered entries.

        Args:
            show_id: Database ID of the parent show.
            entry: Parsed entry describing the file's position.

        Returns:
            Matching :class:`Episode`, or None.
        """
        if entry.episode is None:
            return None

        if entry.season is not None:
            stmt = select(Episode).where(
                Episode.show_id == show_id,
                Episode.season_number == entry.season,
                Episode.episode_number == entry.episode,
            )
            return (await self.session.execute(stmt)).scalar_one_or_none()

        # No season info available — this is an absolute episode number.
        # Try the absolute_episode_number column first (populated via episode groups).
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.absolute_episode_number == entry.episode,
        )
        ep = (await self.session.execute(stmt)).scalar_one_or_none()
        if ep:
            return ep

        # Fall back to season 1 / episode N — wrong for multi-season absolute
        # numbering but the best we can do without episode-group data.
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.season_number == 1,
            Episode.episode_number == entry.episode,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

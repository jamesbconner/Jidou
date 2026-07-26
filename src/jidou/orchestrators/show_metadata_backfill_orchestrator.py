"""Orchestrator for backfilling incomplete TMDB metadata on existing shows."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)

# Fields build_show_fields returns that describe local filesystem
# organization rather than TMDB metadata. Never overwritten by a backfill --
# the show already exists and files may already be organized under its
# current sys_name, unlike a rematch (a deliberate identity change) which
# does intend to update it.
_SKIP_FIELDS = frozenset({"sys_name"})


@dataclass
class MetadataBackfillResult:
    """Result of a metadata backfill run."""

    shows_checked: int
    shows_updated: int
    shows_failed: int
    updated_titles: list[str] = field(default_factory=list)
    failed_titles: list[str] = field(default_factory=list)


class ShowMetadataBackfillOrchestrator:
    """Refetch and reapply TMDB metadata for shows with no genre data.

    Targets shows created via a code path that only had a TMDB search/
    trending card available (``genre_ids``, no full ``genres``/
    ``external_ids``/``episode_groups``/etc.) rather than a full details
    fetch — see ``POST /shows``'s historical behavior, fixed alongside this
    orchestrator. Never touches ``content_type``, ``local_path``,
    ``aliases``, ``aliases_sources``, or ``sys_name``, so a show's existing
    local file organization is unaffected.

    Args:
        session: Active async SQLAlchemy session.
        tmdb: Configured TMDBService instance.
    """

    def __init__(self, session: AsyncSession, tmdb: TMDBService) -> None:
        self.session = session
        self.tmdb = tmdb

    async def run(
        self,
        *,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> MetadataBackfillResult:
        """Backfill TMDB metadata for every show with no genre data.

        Args:
            dry_run: When True, identifies candidates and logs what would
                change without writing anything.
            on_progress: Optional async callback(current, total, message).

        Returns:
            Aggregated MetadataBackfillResult.
        """
        all_shows = list((await self.session.execute(select(Show))).scalars().all())
        # Only `None` means "never backfilled" -- SQL NULL and a JSON null
        # literal both deserialize to Python None, so checking identity in
        # Python after load sidesteps needing to match both shapes in a
        # WHERE clause. An empty list is a legitimate, already-correct
        # "TMDB has no genres for this show" result and must NOT be
        # treated as a candidate again, or a genuinely genre-less show
        # would be re-selected and re-fetched on every future run forever.
        candidates = [s for s in all_shows if s.genres is None]

        total = len(candidates)
        result = MetadataBackfillResult(shows_checked=total, shows_updated=0, shows_failed=0)

        for idx, show in enumerate(candidates, 1):
            if on_progress:
                await on_progress(idx, total, f"Backfilling {show.title}")

            try:
                data = await fetch_show_metadata(self.tmdb, show.tmdb_id, show.media_type)
                fields = build_show_fields(
                    data, show.tmdb_id, show.media_type, existing=show, title_fallback=show.title
                )
            except Exception:
                logger.exception(
                    "Metadata backfill fetch failed for show id=%d tmdb_id=%d",
                    show.id,
                    show.tmdb_id,
                )
                result.shows_failed += 1
                result.failed_titles.append(show.title)
                continue

            if dry_run:
                logger.info(
                    "[dry-run] Would backfill show id=%d (%s): %d genre(s)",
                    show.id,
                    show.title,
                    len(fields.get("genres") or []),
                )
                result.shows_updated += 1
                result.updated_titles.append(show.title)
                continue

            for key, value in fields.items():
                if key in _SKIP_FIELDS:
                    continue
                setattr(show, key, value)

            try:
                await self.session.flush()
                await self.session.commit()
            except Exception:
                logger.exception("Failed to save backfilled metadata for show id=%d", show.id)
                await self.session.rollback()
                result.shows_failed += 1
                result.failed_titles.append(show.title)
                continue

            result.shows_updated += 1
            result.updated_titles.append(show.title)

        return result

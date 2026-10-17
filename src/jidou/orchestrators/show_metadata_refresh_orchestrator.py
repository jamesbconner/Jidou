"""Orchestrator that keeps TMDB-owned ``Show`` metadata fresh over time.

Unlike the one-off ``ShowMetadataBackfillOrchestrator`` (shows with no genres),
this runs on a schedule and on demand: it picks a bounded batch of the stalest
or most suspect shows (see ``metadata_refresh_policy``), refetches them live
from TMDB, and rewrites only the TMDB-owned columns.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.show import Show, show_columns
from jidou.services.callbacks import OnProgress
from jidou.services.metadata_refresh_candidates import load_refresh_facts
from jidou.services.metadata_refresh_policy import RefreshPolicy, select_candidates
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)

# Only columns TMDB owns are ever rewritten. User-curated columns (local_path,
# poster overrides, the active episode group, ...) and derived ones (sys_name,
# episode_group_map) are deliberately outside this mask, so a refresh can't
# disturb local file organisation or manual choices.
_WRITE_FIELDS = show_columns("tmdb") & frozenset(build_show_fields({}, 0, "tv"))


@dataclass
class MetadataRefreshResult:
    """Result of a metadata refresh run.

    Attributes:
        shows_checked: Shows selected for refresh this run.
        shows_updated: Shows successfully refreshed (or planned, in dry run).
        shows_failed: Shows whose fetch or save failed.
        updated_titles: Titles of refreshed shows.
        failed_titles: Titles of failed shows.
        reasons: Count of selected shows by :class:`RefreshReason` name.
    """

    shows_checked: int
    shows_updated: int
    shows_failed: int
    updated_titles: list[str] = field(default_factory=list)
    failed_titles: list[str] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)


def _is_not_found(exc: Exception) -> bool:
    """Whether *exc* is a TMDB 404 (the show no longer exists at that id)."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404


class ShowMetadataRefreshOrchestrator:
    """Refetch and reapply TMDB metadata for the shows most in need of it.

    Args:
        session: Active async SQLAlchemy session.
        tmdb: Configured TMDBService instance.
        now: Clock returning a timezone-aware time; injectable for tests.
    """

    def __init__(
        self,
        session: AsyncSession,
        tmdb: TMDBService,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.session = session
        self.tmdb = tmdb
        self._now = now

    async def refresh_show(self, show: Show, *, dry_run: bool = False) -> dict[str, Any]:
        """Refetch one show live from TMDB and apply its TMDB-owned fields.

        Flushes but does not commit: the caller owns the transaction boundary.

        Args:
            show: Show to refresh.
            dry_run: Fetch and map, but write nothing (no fields, no stamp).

        Returns:
            The full field map built from the TMDB response.

        Raises:
            Exception: Any TMDB fetch error propagates (``httpx.HTTPStatusError``
                for a non-2xx response).
        """
        data = await fetch_show_metadata(
            self.tmdb, show.tmdb_id, show.media_type, bypass_cache=True
        )
        fields = build_show_fields(
            data, show.tmdb_id, show.media_type, existing=show, title_fallback=show.title
        )
        if dry_run:
            return fields

        for key in _WRITE_FIELDS:
            value = fields[key]
            # None (episode_groups) or {} (external_ids) is how
            # fetch_show_metadata reports a failed supplemental fetch; TMDB
            # itself always returns the external_ids keys, null-valued if
            # unknown. Keep whatever is already known rather than erasing it.
            if (key == "episode_groups" and value is None) or (key == "external_ids" and not value):
                continue
            setattr(show, key, value)
        show.metadata_refreshed_at = self._now()
        await self.session.flush()
        return fields

    async def run(
        self,
        *,
        dry_run: bool = False,
        on_progress: OnProgress | None = None,
        policy: RefreshPolicy | None = None,
    ) -> MetadataRefreshResult:
        """Refresh the next batch of due shows.

        Args:
            dry_run: Select and fetch, but write and commit nothing.
            on_progress: Optional async callback(current, total, message).
            policy: Override the settings-derived policy (tests, one-off runs).

        Returns:
            Aggregated :class:`MetadataRefreshResult`.
        """
        policy = policy or RefreshPolicy.from_settings(self._now())
        picked = select_candidates(await load_refresh_facts(self.session, policy), policy)

        result = MetadataRefreshResult(shows_checked=len(picked), shows_updated=0, shows_failed=0)
        if not picked:
            return result
        for _, reason in picked:
            result.reasons[reason.name] = result.reasons.get(reason.name, 0) + 1

        for idx, (facts, reason) in enumerate(picked, 1):
            # Loaded one at a time, not prefetched: a rollback expires every
            # Show already in the session, and touching an expired instance
            # outside the greenlet bridge raises MissingGreenlet. A show loaded
            # after the previous one finished can't have been expired by it.
            show = await self.session.get(Show, facts.show_id)
            if show is None:  # deleted between the facts query and now
                continue
            if on_progress:
                await on_progress(idx, len(picked), f"Refreshing {facts.title}")
            logger.info(
                "Refreshing show metadata show_id=%d reason=%s dry_run=%s",
                facts.show_id,
                reason.name,
                dry_run,
            )
            if await self._refresh_and_commit(show, facts.title, dry_run=dry_run):
                result.shows_updated += 1
                result.updated_titles.append(facts.title)
            else:
                result.shows_failed += 1
                result.failed_titles.append(facts.title)
        return result

    async def _refresh_and_commit(self, show: Show, title: str, *, dry_run: bool) -> bool:
        """Refresh one show in its own SAVEPOINT and commit it.

        Args:
            show: Show to refresh.
            title: Title captured before any rollback could expire *show*.
            dry_run: Skip writes and the commit.

        Returns:
            ``True`` on success, ``False`` if the fetch or save failed.
        """
        # Captured up front: a rollback expires `show`, and a bare attribute
        # read in an except block would then lazy-load outside the greenlet
        # bridge (MissingGreenlet) instead of surfacing the original error.
        show_id = show.id
        try:
            # SAVEPOINT, not session.rollback(): a full rollback would expire
            # every other Show still pending in this run.
            async with self.session.begin_nested():
                await self.refresh_show(show, dry_run=dry_run)
        except Exception as exc:
            logger.exception("Metadata refresh failed for show id=%d", show_id)
            if _is_not_found(exc) and not dry_run:
                await self._stamp_gone(show, show_id)
            return False

        if dry_run:
            return True
        try:
            await self.session.commit()
        except Exception:
            logger.exception("Failed to commit refreshed metadata for show id=%d", show_id)
            await self.session.rollback()
            return False
        return True

    async def _stamp_gone(self, show: Show, show_id: int) -> None:
        """Stamp a show TMDB no longer has, so it isn't retried on every run.

        Fixing a dead id is a manual Fix Match; the job's only responsibility
        is to stop it from crowding out every other candidate.

        Args:
            show: The show whose TMDB id returned 404.
            show_id: Its id, for logging.
        """
        try:
            async with self.session.begin_nested():
                show.metadata_refreshed_at = self._now()
                await self.session.flush()
            await self.session.commit()
            logger.warning("TMDB returned 404 for show id=%d; stamped to avoid retry", show_id)
        except Exception:
            logger.exception("Failed to stamp missing-on-TMDB show id=%d", show_id)
            await self.session.rollback()

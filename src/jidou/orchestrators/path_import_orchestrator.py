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
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import ParsedPathEntry, group_by_show
from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

_INVALID_FS_CHARS = re.compile(r'[\\/:*?"<>|]')

# Strips punctuation (colons, hyphens, apostrophes, etc.) for loose title
# comparison so "Daredevil Born Again" matches TMDB's "Daredevil: Born Again".
_PUNCT = re.compile(r"[^\w\s]")

_LLM_SYSTEM = (
    "You are a filename-to-episode matcher. "
    "Given a show title, a filename, and a numbered episode list, "
    "identify which episode the file belongs to. "
    "Reply with ONLY two integers: season_number episode_number (space-separated). "
    "Example: 2 7\n"
    "If you cannot determine the match, reply with exactly: UNKNOWN"
)

_LLM_SHOW_MATCH_SYSTEM = (
    "You are a TV show title matcher. "
    "Given a directory name and a numbered list of TMDB candidates, "
    "identify which candidate is the same show as the directory. "
    "Directories often omit articles (\"Marvel's\", \"The\") or franchise subtitles "
    "(\"Born Again\") that appear in TMDB titles — treat those as matches. "
    "A sequel or spin-off with a shared word is NOT a match unless the directory "
    "clearly refers to that specific entry. "
    'Example: "Daredevil" matches "Marvel\'s Daredevil" but NOT "Daredevil: Born Again". '
    "Reply with ONLY the candidate number (1, 2, 3, ...) or NONE if no candidate matches."
)


def _sanitize_sys_name(title: str) -> str:
    return _INVALID_FS_CHARS.sub("_", title).strip()


def _normalize_title(s: str) -> str:
    """Lowercase and strip punctuation for loose title comparison.

    Allows directory names like "Daredevil Born Again" to match TMDB titles
    like "Daredevil: Born Again" without false-positives from shorter prefixes.

    Args:
        s: Title string to normalize.

    Returns:
        Normalized string with punctuation removed and whitespace collapsed.
    """
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", s).lower()).strip()


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
        llm: LLMService | None = None,
        on_event: Callable[[str, str, dict[str, object] | None], Awaitable[None]] | None = None,
    ) -> None:
        self.session = session
        self.tmdb = tmdb
        self.content_type = content_type
        self.dry_run = dry_run
        self.llm = llm
        self.on_event = on_event

    async def _emit(
        self,
        level: str,
        msg: str,
        ctx: dict[str, object] | None = None,
    ) -> None:
        if self.on_event:
            await self.on_event(level, msg, ctx)

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
            await self._emit("info", f"Not in DB — searching TMDB for '{show_dir}'")
            show, action = await self._tmdb_create_show(show_dir)
            show_result.action = action
        else:
            show_result.action = "found"
            await self._emit(
                "info",
                f"Found in DB: '{show.title}'",
                {"show_id": show.id, "tmdb_id": show.tmdb_id},
            )
            logger.info("Found existing show %r (id=%d) for dir %r", show.title, show.id, show_dir)
            # If episodes haven't been synced yet, do it now so file matching can proceed.
            if not self.dry_run:
                ep_count = await self.session.scalar(
                    select(func.count()).select_from(Episode).where(Episode.show_id == show.id)
                )
                if ep_count == 0:
                    await self._emit(
                        "info", f"No episodes synced yet — fetching from TMDB for '{show.title}'"
                    )
                    try:
                        await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(show)
                    except Exception as exc:
                        await self._emit("error", f"Episode sync failed for '{show.title}': {exc}")
                        logger.exception("Episode sync failed for show id=%d", show.id)

        if show is None:
            await self._emit(
                "warn", f"No TMDB match found for '{show_dir}' — {len(entries)} file(s) unmatched"
            )
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
            ep = await self._find_episode(show.id, show.title, entry)
            if ep is not None:
                newly_tracked = not ep.file_tracked
                if not self.dry_run:
                    ep.file_tracked = True
                    # Only overwrite tracking metadata on first track; preserve
                    # match/download metadata from later non-import tracking.
                    if newly_tracked:
                        ep.file_tracked_at = datetime.now(UTC)
                        ep.tracked_filename = entry.raw_path
                        ep.tracked_source = "import"
                if newly_tracked:
                    show_result.episodes_tracked += 1
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

        if show_result.episodes_unmatched:
            await self._emit(
                "warn",
                f"{show_result.episodes_unmatched} unmatched file(s) for '{show.title}'",
                {
                    "episodes_tracked": show_result.episodes_tracked,
                    "episodes_unmatched": show_result.episodes_unmatched,
                },
            )
        else:
            await self._emit(
                "info",
                f"Tracked {show_result.episodes_tracked} episode(s) for '{show.title}'",
            )

        if not self.dry_run:
            await self.session.commit()
        return show_result

    async def _db_find_show(self, name: str) -> Show | None:
        """Look up a show in the database by title or alias.

        Uses exact case-insensitive equality (not substring matching) so that
        "Daredevil" cannot accidentally resolve to "Daredevil: Born Again".

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

        # Exact case-insensitive title match.  Substring matching (ILIKE '%x%')
        # would cause "Daredevil" to match "Daredevil: Born Again".
        stmt = select(Show).where(func.lower(Show.title) == normalised).order_by(Show.id).limit(1)
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
        await self._emit("info", f"Calling TMDB search for '{show_dir}'")
        try:
            results = await self.tmdb.search(show_dir, media_type="tv")
        except Exception as exc:
            await self._emit("error", f"TMDB search failed for '{show_dir}': {exc}")
            logger.warning("TMDB search failed for %r", show_dir)
            return None, "not_found"

        candidates = [r for r in results.get("results", []) if r.get("media_type") in ("tv", None)]
        if not candidates:
            await self._emit("warn", f"TMDB returned no results for '{show_dir}'")
            logger.warning("No TMDB results for directory %r", show_dir)
            return None, "not_found"

        # Normalized exact match wins; otherwise take the top relevance result.
        # Normalization strips punctuation so "Daredevil Born Again" matches
        # TMDB's "Daredevil: Born Again" without matching the shorter "Daredevil".
        # Scan ALL candidates — not just the first five — because TMDB's recency
        # bias can rank a newer show (e.g. "Daredevil: Born Again") above an older
        # exact match (e.g. the 2015 "Daredevil") when both appear in the results.
        show_dir_norm = _normalize_title(show_dir)
        best = candidates[0]
        exact_match = False
        for c in candidates:
            if _normalize_title(c.get("name", "")) == show_dir_norm:
                best = c
                exact_match = True
                break

        tmdb_id: int = best["id"]
        top_names: list[str | None] = [c.get("name") for c in candidates[:5]]
        if exact_match:
            await self._emit(
                "info",
                f"TMDB matched '{best.get('name')}' (id={tmdb_id})",
                {"tmdb_id": tmdb_id, "candidates": len(candidates), "match": "exact"},
            )
        else:
            # No normalized exact match — ask the LLM to disambiguate before
            # falling back to the top popularity result.
            llm_pick = await self._llm_pick_candidate(show_dir, candidates)
            if llm_pick is not None:
                best = llm_pick
                tmdb_id = best["id"]
                await self._emit(
                    "info",
                    f"LLM matched '{best.get('name')}' (id={tmdb_id}) for '{show_dir}'",
                    {"tmdb_id": tmdb_id, "candidates": len(candidates), "match": "llm"},
                )
            else:
                await self._emit(
                    "warn",
                    (
                        f"No exact TMDB match for '{show_dir}' in {len(candidates)} result(s) "
                        f"— falling back to top result '{best.get('name')}' (id={tmdb_id})"
                    ),
                    {
                        "tmdb_id": tmdb_id,
                        "candidates": len(candidates),
                        "match": "fallback",
                        "top_candidates": top_names,
                    },
                )

        # Fetch full show details.
        try:
            data = await self.tmdb.get_details(tmdb_id, media_type="tv")
        except Exception as exc:
            await self._emit("error", f"TMDB get_details failed for id={tmdb_id}: {exc}")
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
            await self._emit("info", f"[dry-run] Would create show '{title}' (tmdb_id={tmdb_id})")
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
                await self._emit("info", f"Show '{title}' already existed (concurrent create)")
                return fallback, "found"
            return None, "not_found"

        await self._emit(
            "info",
            f"Created show '{title}' (id={show.id}, tmdb_id={tmdb_id})",
            {"show_id": show.id, "tmdb_id": tmdb_id},
        )
        logger.info("Created show %r (tmdb_id=%d, id=%d)", title, tmdb_id, show.id)

        # Sync all episodes from TMDB so episode matching can proceed.
        await self._emit("info", f"Syncing episodes for '{title}' from TMDB")
        try:
            await TMDBOrchestrator(self.session, self.tmdb).sync_show_episodes(show)
            ep_count = await self.session.scalar(
                select(func.count()).select_from(Episode).where(Episode.show_id == show.id)
            )
            await self._emit("info", f"Synced {ep_count} episodes for '{title}'")
        except Exception as exc:
            await self._emit("error", f"Episode sync failed for '{title}': {exc}")
            logger.exception("Episode sync failed for %r (tmdb_id=%d)", title, tmdb_id)
            # Show row exists; proceed to episode matching with whatever was synced.

        return show, "created"

    async def _find_episode(
        self,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
    ) -> Episode | None:
        """Match a parsed path entry to an Episode row.

        Lookup priority:
        1. Season + episode (standard S##E## match).
        2. Absolute episode number column (populated via TMDB episode groups).
        3. ROW_NUMBER() window — sequential position across all non-special episodes.
        4. LLM fallback — filename + full episode list sent to the configured LLM.

        Steps 2-4 are only reached when no season is known, or when the season-based
        lookup (step 1) finds nothing.

        Args:
            show_id: Database ID of the parent show.
            show_title: Show title for the LLM prompt context.
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
            ep = (await self.session.execute(stmt)).scalar_one_or_none()
            if ep is not None:
                return ep
            # S##E## miss with an explicit season > 1 means the episode is
            # genuinely absent — absolute/ROW_NUMBER fallbacks would map to the
            # wrong episode in the overall sequence, so go straight to LLM.
            if entry.season > 1:
                return await self._llm_match(show_id, show_title, entry)
            # Season 1 directory: the episode number may still be a continuous
            # absolute count (e.g. a show with all 148 episodes in Season 01).
            # Fall through to absolute-number lookups before the LLM.

        # No season info — this is an absolute episode number.
        # Try the absolute_episode_number column first (populated via episode groups).
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.absolute_episode_number == entry.episode,
        )
        ep = (await self.session.execute(stmt)).scalar_one_or_none()
        if ep is not None:
            return ep

        # Compute a sequential absolute number by ordering all non-special episodes
        # by (season_number, episode_number) and matching on row position.  This
        # handles shows like HxH where fansub filenames use a continuous count but
        # TMDB stores episodes per-season and does not populate absolute_number.
        numbered = (
            select(
                Episode.id,
                func.row_number()
                .over(order_by=[Episode.season_number, Episode.episode_number])
                .label("row_num"),
            )
            .where(Episode.show_id == show_id, Episode.season_number > 0)
            .subquery()
        )
        stmt = (
            select(Episode)
            .join(numbered, Episode.id == numbered.c.id)
            .where(numbered.c.row_num == entry.episode)
        )
        ep = (await self.session.execute(stmt)).scalar_one_or_none()
        if ep is not None:
            return ep

        return await self._llm_match(show_id, show_title, entry)

    async def _llm_pick_candidate(
        self,
        show_dir: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Ask the LLM to pick the best TMDB candidate for show_dir.

        Only called when exact normalized matching fails across all candidates.
        Handles cases like "Daredevil" → "Marvel's Daredevil" where the directory
        omits a leading article or franchise tag that TMDB includes in the title.

        Args:
            show_dir: Show directory name to match.
            candidates: TMDB search result dicts, each with at least ``"name"``.

        Returns:
            The chosen candidate dict, or None if the LLM is unavailable or
            cannot determine a match.
        """
        if self.llm is None or not self.llm.is_available():
            return None

        shortlist = candidates[:10]
        lines = [
            f"{i + 1}. {c.get('name')} ({str(c.get('first_air_date') or '')[:4] or '?'})"
            for i, c in enumerate(shortlist)
        ]
        prompt = f'Directory: "{show_dir}"\n\nCandidates:\n' + "\n".join(lines)

        try:
            response = await self.llm.complete(prompt=prompt, system=_LLM_SHOW_MATCH_SYSTEM)
        except Exception:
            logger.warning("LLM show-match failed for %r", show_dir)
            return None

        if response is None:
            return None

        text = response.content.strip()
        if text == "NONE":
            return None

        try:
            idx = int(text) - 1
        except ValueError:
            logger.warning("LLM returned unexpected format %r for show dir %r", text, show_dir)
            return None

        if 0 <= idx < len(shortlist):
            return shortlist[idx]

        logger.warning("LLM returned out-of-range index %d for show dir %r", idx + 1, show_dir)
        return None

    async def _llm_match(
        self,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
    ) -> Episode | None:
        """Ask the LLM to identify the episode from the filename.

        Only called after all DB-based lookup strategies have failed.

        Args:
            show_id: Database ID of the parent show.
            show_title: Show title for prompt context.
            entry: Parsed entry with the raw file path.

        Returns:
            Matching :class:`Episode`, or None if LLM is unavailable or unconfident.
        """
        if self.llm is None or not self.llm.is_available():
            return None

        eps = list(
            (
                await self.session.execute(
                    select(Episode)
                    .where(Episode.show_id == show_id)
                    .order_by(Episode.season_number, Episode.episode_number)
                )
            )
            .scalars()
            .all()
        )
        if not eps:
            return None

        ep_list = "\n".join(
            f"S{ep.season_number:02d}E{ep.episode_number:02d}: {ep.name}" for ep in eps[:500]
        )
        filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        prompt = f"Show: {show_title}\nFilename: {filename}\n\nEpisodes:\n{ep_list}"

        try:
            response = await self.llm.complete(prompt=prompt, system=_LLM_SYSTEM)
        except Exception:
            logger.warning("LLM match failed for %r in show %r", filename, show_title)
            return None

        if response is None:
            return None

        text = response.content.strip()
        if text == "UNKNOWN":
            return None

        parts = text.split()
        if len(parts) != 2:
            logger.warning("LLM returned unexpected format %r for %r", text, filename)
            return None

        try:
            season, episode_num = int(parts[0]), int(parts[1])
        except ValueError:
            logger.warning("LLM returned non-integer response %r for %r", text, filename)
            return None

        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.season_number == season,
            Episode.episode_number == episode_num,
        )
        ep = (await self.session.execute(stmt)).scalar_one_or_none()
        if ep is not None:
            logger.info(
                "LLM matched %r -> S%02dE%02d for show %r",
                filename,
                season,
                episode_num,
                show_title,
            )
        return ep

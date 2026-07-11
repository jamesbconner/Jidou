"""Orchestrator for importing episode file path lists into the database.

For each unique show directory found in the path list:

1. Searches the DB for an existing show by title or alias.
2. If not found, searches TMDB, creates the Show row, and syncs its episodes.
3. Matches each parsed file to an Episode row by season/episode number
   (or absolute episode number as a fallback).
4. Sets ``episode.file_tracked = True`` for every matched episode.
5. Creates a display-only, already-ROUTED ``DownloadedFile`` for each
   newly-tracked episode, so it shows up correctly on the Files page. This
   row never participates in the match/route pipeline — reassignment for
   imported episodes still goes through the ``assign-import`` endpoint.

Japanese (romaji/kanji) directory names are passed directly to TMDB's
multi-language search, which resolves them to English titles.  The original
directory name is stored in ``show.aliases`` when it differs from the English
title so future lookups (parse orchestrator, manual search) hit the GIN index.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.services.episode_tracking import mark_episode_tracked
from jidou.services.filename_parser import parse_filename
from jidou.services.llm_json import parse_llm_json
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import ParsedPathEntry, group_by_show
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)

# Strips punctuation (colons, hyphens, apostrophes, etc.) for loose title
# comparison so "Daredevil Born Again" matches TMDB's "Daredevil: Born Again".
_PUNCT = re.compile(r"[^\w\s]")

_LLM_SYSTEM = (
    "You are a filename-to-episode matcher. "
    "Given a show title, a filename, and a numbered episode list, "
    "identify which episode the file belongs to. "
    "Reply with ONLY a compact JSON object: "
    '{"season": <integer or null>, "episode": <integer or null>}. '
    "Use null for season or episode if you cannot determine the match. "
    "No other text, no markdown, no explanation."
)

_LLM_SHOW_MATCH_SYSTEM = (
    "You are a TV show title matcher. "
    "Given a directory name and a numbered list of TMDB candidates, "
    "identify which candidate is the same show as the directory. "
    'Directories often omit articles ("Marvel\'s", "The") or franchise subtitles '
    '("Born Again") that appear in TMDB titles — treat those as matches. '
    "A sequel or spin-off with a shared word is NOT a match unless the directory "
    "clearly refers to that specific entry. "
    'Example: "Daredevil" matches "Marvel\'s Daredevil" but NOT "Daredevil: Born Again". '
    'Reply with ONLY a compact JSON object: {"match": <candidate number (1, 2, 3, ...) or null>}. '
    "Use null if no candidate matches. No other text, no markdown, no explanation."
)

_LLM_EPISODE_PARSE_SYSTEM = (
    "You are a TV episode filename parser. Extract only the season and "
    "episode numbers from the filename.\n\n"
    "Rules:\n"
    "- A bare trailing number with no other marker is the episode number, "
    'never the season (e.g. "Show 09" -> episode 9, season null).\n'
    "- Only set season when it is explicitly marked (S02, Season 2, "
    "2nd Season, etc.). Never infer season from a bare number.\n"
    '- Version suffixes like "01v2" mean episode 1.\n'
    "- Tokens like NCED, NCOP, OP, ED, PV, CM, SP, OVA, or OAD indicate "
    "non-episode bonus content, not a numbered episode, unless an explicit "
    "SxxEyy or E## marker is also present — set episode to null for these.\n"
    "- If you cannot determine the episode with confidence, set episode to "
    "null rather than guessing.\n\n"
    "Reply with ONLY a compact JSON object: "
    '{"season": <integer or null>, "episode": <integer or null>}. '
    "No other text, no markdown, no explanation."
)

_LLM_MATCH_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "episode_match",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["season", "episode"],
            "additionalProperties": False,
        },
    },
}

_LLM_SHOW_MATCH_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "show_match",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "match": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["match"],
            "additionalProperties": False,
        },
    },
}

_LLM_EPISODE_PARSE_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "episode_parse",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "season": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "episode": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["season", "episode"],
            "additionalProperties": False,
        },
    },
}


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


def _agrees_with_show(name: str, show: Show) -> bool:
    """Return True when *name* refers to the same show as *show*.

    Reuses the same normalized-title/alias matching semantics as
    ``_db_find_show``, so a filename-extracted show name is treated as
    agreeing whenever it would have independently resolved to the same show.

    Args:
        name: Extracted show name to check (e.g. from ``parse_filename``).
        show: The already-resolved show to check agreement against.

    Returns:
        True if *name* normalizes to the same title as *show*, or is one of
        its known aliases.
    """
    if _normalize_title(name) == _normalize_title(show.title):
        return True
    normalised = name.strip().lower()
    return bool(show.aliases and normalised in show.aliases)


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
    unmatched_paths: list[str] = field(default_factory=list)


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
        if self.llm is None or not self.llm.is_available():
            await self._emit(
                "warn",
                "LLM not configured or unavailable — filenames that regex can't "
                "parse, and shows TMDB can't match exactly, will not get an LLM "
                "fallback attempt for this run",
            )

        result = PathImportResult()
        grouped = group_by_show(entries)
        result.shows_processed = len(grouped)
        total = len(grouped)

        for idx, (show_dir, show_entries) in enumerate(grouped.items(), 1):
            if on_progress:
                await on_progress(idx, total, f"Importing {show_dir}")

            # Usually one result per directory; more if per-file show-name
            # confirmation split off files belonging to a different show.
            show_results = await self._import_show(show_dir, show_entries)
            for show_result in show_results:
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
    ) -> list[ShowImportResult]:
        """Import one show directory, splitting off files that don't belong.

        The directory name is a good indicator of show identity but isn't
        actually part of the media itself. Every entry's own filename is
        checked (via the shared filename-parsing service) against the
        directory-resolved show; a file whose own name disagrees is pulled
        out and independently resolved/matched against its own show instead
        of being silently absorbed into the directory's show.

        Only an LLM-confirmed disagreement triggers a split. The heuristic
        regex fallback (used when no LLM is configured, or a call fails) is
        far too unreliable for this — a generic filename with no show title
        in it at all (e.g. "extras.mkv") heuristically "extracts" its own
        cleaned name as show_name, which would otherwise disagree with every
        real show and split off a rename-worthy fraction of every import.

        Args:
            show_dir: Show directory name (used as the primary search key).
            entries: All parsed file entries under this directory.

        Returns:
            One :class:`ShowImportResult` per resolved show — normally just
            one (the whole directory is one show), but more if the
            directory turned out to contain files from multiple shows.
        """
        primary_show, action = await self._resolve_show(show_dir)

        if primary_show is None:
            return [await self._process_show_entries(show_dir, None, action, entries)]

        matched: list[ParsedPathEntry] = []
        mismatched: dict[str, list[ParsedPathEntry]] = {}
        mismatched_display: dict[str, str] = {}

        for entry in entries:
            filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
            try:
                parsed = await parse_filename(filename, self.llm)
            except Exception:
                # One entry's parse failure must not abort the whole show's
                # import batch -- fall back to trusting the directory, same
                # as the not-llm_ok / no-show-name cases below.
                logger.exception(
                    "Per-file parse failed for %r; trusting directory-resolved show", filename
                )
                matched.append(entry)
                continue
            if (
                not parsed.llm_ok
                or parsed.show_name is None
                or _agrees_with_show(parsed.show_name, primary_show)
            ):
                matched.append(entry)
            else:
                norm = _normalize_title(parsed.show_name)
                mismatched.setdefault(norm, []).append(entry)
                mismatched_display.setdefault(norm, parsed.show_name)

        results = [await self._process_show_entries(show_dir, primary_show, action, matched)]

        for norm, sub_entries in mismatched.items():
            display_name = mismatched_display[norm]
            await self._emit(
                "warn",
                f"{len(sub_entries)} file(s) under '{show_dir}' appear to belong to "
                f"'{display_name}' instead — resolving separately",
                {"directory": show_dir, "extracted_name": display_name, "count": len(sub_entries)},
            )
            secondary_show, secondary_action = await self._resolve_show(display_name)
            results.append(
                await self._process_show_entries(
                    display_name,
                    secondary_show,
                    secondary_action,
                    sub_entries,
                    set_local_path=False,
                )
            )

        return results

    async def _resolve_show(self, name: str) -> tuple[Show | None, str]:
        """Find or create a show by name: DB lookup first, then TMDB search/create.

        Shared by the primary directory-derived resolution and any secondary
        per-file-derived resolution triggered by a show-name mismatch.

        Args:
            name: Show name to resolve — a directory name, or a per-file
                extracted show name.

        Returns:
            ``(show, action)`` where action is ``"found"``, ``"created"``,
            or ``"not_found"``.
        """
        show = await self._db_find_show(name)

        if show is None:
            await self._emit("info", f"Not in DB — searching TMDB for '{name}'")
            return await self._tmdb_create_show(name)

        await self._emit(
            "info",
            f"Found in DB: '{show.title}'",
            {"show_id": show.id, "tmdb_id": show.tmdb_id},
        )
        logger.info("Found existing show %r (id=%d) for name %r", show.title, show.id, name)
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

        return show, "found"

    async def _process_show_entries(
        self,
        label: str,
        show: Show | None,
        action: str,
        entries: list[ParsedPathEntry],
        set_local_path: bool = True,
    ) -> ShowImportResult:
        """Match a resolved show's entries to episodes and mark them tracked.

        Args:
            label: Display name for this result — the directory name, or the
                per-file extracted name for a split-off secondary group.
            show: The resolved show, or None if resolution failed entirely.
            action: ``"found"``, ``"created"``, or ``"not_found"`` from resolution.
            entries: Parsed file entries to match against this show.
            set_local_path: Whether to auto-populate ``show.local_path`` from
                ``entries[0].show_root`` when unset. False for a split-off
                secondary group — ``show_root`` reflects the *directory's*
                root (the primary show's location), not this show's, so
                auto-setting it here would point the wrong show at the
                primary show's library folder. The show is still fully
                created/matched; only the auto-path step is skipped, same as
                the existing "content_type unknown" skip elsewhere.

        Returns:
            :class:`ShowImportResult` for this show/entries group.
        """
        show_result = ShowImportResult(show_dir=label, action=action)

        if show is None:
            await self._emit(
                "warn", f"No TMDB match found for '{label}' — {len(entries)} file(s) unmatched"
            )
            logger.warning("Could not resolve show for %r", label)
            show_result.episodes_unmatched = len(entries)
            show_result.unmatched_paths = [e.raw_path for e in entries]
            return show_result

        show_result.tmdb_id = show.tmdb_id
        show_result.tmdb_title = show.title

        # Persist the show's root directory path if not already set.
        if set_local_path and not self.dry_run and show.local_path is None and entries:
            show.local_path = entries[0].show_root
            logger.debug("Set local_path=%r for show id=%d", show.local_path, show.id)
        elif not set_local_path and not self.dry_run and show.local_path is None:
            await self._emit(
                "warn",
                f"'{show.title}' was split off from a mismatched directory — "
                "local_path was not auto-set; configure it manually via "
                f"PATCH /shows/{show.id}",
                {"show_id": show.id},
            )
            logger.warning(
                "Cannot auto-set local_path for split-off show id=%d (%r): "
                "source directory does not reflect this show's location",
                show.id,
                show.title,
            )

        # In dry-run mode, a newly "created" show has no database id and no
        # synced episodes yet, so _find_episode would query show_id=NULL and
        # return nothing.  Estimate from the parsed entries instead.
        if self.dry_run and show.id is None:
            for entry in entries:
                if entry.episode is not None:
                    show_result.episodes_tracked += 1
                else:
                    show_result.episodes_unmatched += 1
                    show_result.unmatched_paths.append(entry.raw_path)
            return show_result

        # Match each file entry to an Episode row.
        for entry in entries:
            ep, resolved_season, resolved_episode = await self._find_episode(
                show.id, show.title, entry
            )
            if ep is not None:
                newly_tracked = not ep.file_tracked
                if not self.dry_run:
                    # Only overwrite tracking metadata on first track; preserve
                    # match/download metadata from later non-import tracking.
                    if newly_tracked:
                        mark_episode_tracked(ep, entry.raw_path, "import")
                        await self._create_synthetic_import_file(show.id, ep.id, entry.raw_path)
                    else:
                        ep.file_tracked = True
                if newly_tracked:
                    show_result.episodes_tracked += 1
            else:
                filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
                # resolved_season/resolved_episode reflect any LLM adjustment made
                # inside _find_episode — entry.season/entry.episode would only ever
                # show the pre-LLM regex output, hiding whether an LLM fallback was
                # even attempted or what it returned.
                s_label = f"S{resolved_season:02d}" if resolved_season is not None else "S?"
                e_label = f"E{resolved_episode:02d}" if resolved_episode is not None else "E?"
                show_result.episodes_unmatched += 1
                show_result.unmatched_paths.append(entry.raw_path)
                await self._emit(
                    "warn",
                    f"No match: {filename} ({s_label}{e_label})",
                    {
                        "path": entry.raw_path,
                        "season": resolved_season,
                        "episode": resolved_episode,
                    },
                )
                logger.debug(
                    "No episode match: show=%r label=%r season=%s episode=%s abs=%s path=%r",
                    show.title,
                    label,
                    resolved_season,
                    resolved_episode,
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

    async def _create_synthetic_import_file(
        self,
        show_id: int,
        episode_id: int,
        raw_path: str,
    ) -> None:
        """Create a display-only, already-ROUTED DownloadedFile for an imported episode.

        Path-imported files are already at their final library location — they
        were never downloaded or routed by Jidou itself — so this row exists
        purely to make them show up correctly on the Files page. It uses the
        ``synthetic-import://`` ``remote_path`` convention already recognised
        elsewhere: the episode-listing query excludes these rows from the
        backing-files list (so Fix Match's "Imported" chip is unaffected), and
        RouteOrchestrator already no-ops a move when source equals destination.

        Imported episodes continue to use the ``assign-import`` endpoint for
        reassignment, not ``begin-rematch`` — this row never participates in
        the match/route pipeline.

        Args:
            show_id: Database ID of the parent show.
            episode_id: Database ID of the matched episode.
            raw_path: The file's existing absolute path (already at its final
                on-disk location).
        """
        synthetic_remote_path = f"synthetic-import://{raw_path}"
        existing_stmt = select(DownloadedFile).where(
            DownloadedFile.remote_path == synthetic_remote_path
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return

        filename = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            async with self.session.begin_nested():
                self.session.add(
                    DownloadedFile(
                        show_id=show_id,
                        episode_id=episode_id,
                        original_filename=filename,
                        remote_path=synthetic_remote_path,
                        local_path=raw_path,
                        status=FileStatus.ROUTED,
                    )
                )
        except IntegrityError:
            logger.debug("Synthetic file record already exists (race): %s", raw_path)

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

        # Fetch full show details (external_ids/episode_groups included).
        try:
            data = await fetch_show_metadata(self.tmdb, tmdb_id, "tv")
        except Exception as exc:
            await self._emit("error", f"TMDB get_details failed for id={tmdb_id}: {exc}")
            logger.warning("TMDB get_details failed for tmdb_id=%d", tmdb_id)
            return None, "not_found"

        title: str = data.get("name") or show_dir

        # Store the directory name as a user alias when it differs from the
        # English title.  Written into both columns from the start so
        # generate_aliases (called below) preserves it via aliases_sources["user"]
        # rather than relying on the migration guard for a null aliases_sources.
        aliases: list[str] = []
        aliases_sources: dict[str, list[str]] | None = None
        if show_dir.lower() != title.lower():
            dir_alias = show_dir.lower()
            aliases.append(dir_alias)
            aliases_sources = {"user": [dir_alias]}

        fields = build_show_fields(data, tmdb_id, "tv", title_fallback=show_dir)
        show = Show(
            **fields,
            content_type=self.content_type,
            aliases=aliases or None,
            aliases_sources=aliases_sources,
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

        # Generate TMDB alternative-title aliases and LLM aliases.  The
        # directory-name alias (stored in show.aliases at construction time when
        # it differs from the English title) is preserved via the migration guard
        # in generate_aliases (aliases_sources is None → fold into user bucket).
        try:
            from jidou.orchestrators.alias_orchestrator import generate_aliases

            await generate_aliases(show, self.tmdb, llm=self.llm)
            await self.session.flush()
            await self._emit("info", f"Generated aliases for '{title}'")
        except Exception:
            logger.warning(
                "Alias generation failed for %r (tmdb_id=%d); "
                "aliases can be regenerated via the Manage Aliases modal",
                title,
                tmdb_id,
                exc_info=True,
            )

        return show, "created"

    async def _llm_parse_episode(
        self,
        filename: str,
        known_season: int | None = None,
    ) -> tuple[int | None, int | None]:
        """Use the LLM to extract season and episode numbers from a filename.

        Called when regex parsing in :mod:`~jidou.services.path_parser` returns
        ``episode=None``.  Uses a lightweight prompt that asks only for season
        and episode — the show is already known from the directory.

        Args:
            filename: Basename of the episode file.
            known_season: Season already inferred from the directory path, if any.
                Passed as a grounding hint to reduce hallucination.

        Returns:
            ``(season, episode)`` tuple; either value may be None.
        """
        if self.llm is None or not self.llm.is_available():
            return None, None

        hint = f"\nKnown season from directory: {known_season}" if known_season is not None else ""
        try:
            response = await self.llm.complete(
                prompt=f"Filename: {filename}{hint}",
                system=_LLM_EPISODE_PARSE_SYSTEM,
                response_format=_LLM_EPISODE_PARSE_RESPONSE_FORMAT,
            )
        except Exception as exc:
            logger.warning("LLM episode-parse failed for %r", filename)
            await self._emit("warn", f"LLM episode-parse failed for '{filename}': {exc}")
            return None, None

        if response is None:
            await self._emit("warn", f"LLM episode-parse returned no response for '{filename}'")
            return None, None

        parsed = parse_llm_json(response.content)
        if parsed is None:
            logger.warning(
                "LLM returned invalid JSON for episode parse of %r: %r", filename, response.content
            )
            await self._emit(
                "warn",
                f"LLM episode-parse returned invalid JSON for '{filename}': {response.content!r}",
            )
            return None, None

        if not isinstance(parsed, dict):
            logger.warning(
                "LLM returned non-dict JSON for episode parse of %r: %r", filename, response.content
            )
            content = response.content
            await self._emit(
                "warn", f"LLM episode-parse returned non-object JSON for '{filename}': {content!r}"
            )
            return None, None

        raw_season = parsed.get("season")
        raw_episode = parsed.get("episode")
        try:
            season = int(raw_season) if raw_season is not None else None
            episode = int(raw_episode) if raw_episode is not None else None
        except (TypeError, ValueError):
            logger.warning("LLM returned non-integer S/E for %r: %r", filename, parsed)
            await self._emit(
                "warn", f"LLM episode-parse returned non-integer season/episode for '{filename}'"
            )
            return None, None

        logger.debug("LLM episode-parse: %r → season=%s episode=%s", filename, season, episode)
        await self._emit(
            "info",
            f"LLM episode-parse: '{filename}' -> season={season} episode={episode}",
            {"filename": filename, "season": season, "episode": episode},
        )
        return season, episode

    async def _absolute_lookup(self, show_id: int, absolute_number: int) -> Episode | None:
        """Look up an Episode by absolute (series-wide) episode number.

        Tries the ``absolute_episode_number`` column first (populated via
        TMDB episode groups), then falls back to a computed sequential
        position — ordering all non-special episodes by
        ``(season_number, episode_number)`` and matching on row position.
        The fallback handles shows like HxH where fansub filenames use a
        continuous count but TMDB stores episodes per-season and doesn't
        populate ``absolute_episode_number``.

        Args:
            show_id: Database ID of the parent show.
            absolute_number: The absolute episode number to look up.

        Returns:
            Matching :class:`Episode`, or None.
        """
        stmt = select(Episode).where(
            Episode.show_id == show_id,
            Episode.absolute_episode_number == absolute_number,
        )
        ep = (await self.session.execute(stmt)).scalar_one_or_none()
        if ep is not None:
            return ep

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
            .where(numbered.c.row_num == absolute_number)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _find_episode(
        self,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Match a parsed path entry to an Episode row.

        Lookup priority:
        1. If regex gave no episode, ask the LLM to parse season/episode from
           the filename alone (lightweight prompt, no episode list needed).
        2. Season + episode DB match (standard S##E## lookup).
        3. Absolute episode number column (populated via TMDB episode groups).
        4. ROW_NUMBER() window — sequential position across all non-special episodes.
        5. LLM episode-list match — filename + full episode list sent to the LLM.

        Steps 3-4 are also tried on a season>1 S##E## miss, using
        ``entry.absolute_candidate`` when set (the raw joined number from an
        ambiguous compact-code guess, e.g. "212" guessed as S02E12) or the
        bare episode number otherwise — the show's real data may use
        absolute numbering even though the filename encodes a season.

        Args:
            show_id: Database ID of the parent show.
            show_title: Show title for the LLM prompt context.
            entry: Parsed entry describing the file's position.

        Returns:
            ``(episode, season, episode_number)`` where ``episode`` is the
            matching :class:`Episode` or None, and ``season``/``episode_number``
            are the best-effort season/episode this attempt resolved to —
            including any LLM adjustment — for callers to log accurately even
            when no match was found.
        """
        season = entry.season
        episode = entry.episode

        if episode is None:
            filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
            llm_season, llm_episode = await self._llm_parse_episode(filename, season)
            if llm_episode is None:
                # The LLM may still have proposed a season even without an
                # episode — surface it rather than silently discarding it.
                return None, season if season is not None else llm_season, episode
            episode = llm_episode
            if season is None:
                season = llm_season

        absolute_guess = (
            entry.absolute_candidate if entry.absolute_candidate is not None else episode
        )

        if season is not None:
            stmt = select(Episode).where(
                Episode.show_id == show_id,
                Episode.season_number == season,
                Episode.episode_number == episode,
            )
            ep = (await self.session.execute(stmt)).scalar_one_or_none()
            if ep is not None:
                return ep, season, episode
            if season > 1:
                # Before giving up to the LLM, try absolute-number lookups —
                # the show's real data may use absolute numbering (or this
                # season/episode pair may itself be an ambiguous compact-code
                # guess whose raw number is the correct absolute episode).
                abs_ep = await self._absolute_lookup(show_id, absolute_guess)
                if abs_ep is not None:
                    return abs_ep, season, episode
                llm_ep, llm_season, llm_episode_num = await self._llm_match(
                    show_id, show_title, entry
                )
                return (
                    llm_ep,
                    llm_season if llm_season is not None else season,
                    llm_episode_num if llm_episode_num is not None else episode,
                )
            # Season 1 directory: the episode number may still be a continuous
            # absolute count (e.g. a show with all 148 episodes in Season 01).
            # Fall through to absolute-number lookups before the LLM.

        # No season info — this is an absolute episode number.
        abs_ep = await self._absolute_lookup(show_id, absolute_guess)
        if abs_ep is not None:
            return abs_ep, season, episode

        llm_ep, llm_season, llm_episode_num = await self._llm_match(show_id, show_title, entry)
        return (
            llm_ep,
            llm_season if llm_season is not None else season,
            llm_episode_num if llm_episode_num is not None else episode,
        )

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
            response = await self.llm.complete(
                prompt=prompt,
                system=_LLM_SHOW_MATCH_SYSTEM,
                response_format=_LLM_SHOW_MATCH_RESPONSE_FORMAT,
            )
        except Exception as exc:
            logger.warning("LLM show-match failed for %r", show_dir)
            await self._emit("warn", f"LLM show-match failed for '{show_dir}': {exc}")
            return None

        if response is None:
            await self._emit("warn", f"LLM show-match returned no response for '{show_dir}'")
            return None

        parsed = parse_llm_json(response.content)
        if parsed is None:
            logger.warning(
                "LLM returned invalid JSON for show-match of %r: %r", show_dir, response.content
            )
            await self._emit(
                "warn",
                f"LLM show-match returned invalid JSON for '{show_dir}': {response.content!r}",
            )
            return None

        raw_match = parsed.get("match") if isinstance(parsed, dict) else None
        if raw_match is None:
            await self._emit("warn", f"LLM show-match could not pick a candidate for '{show_dir}'")
            return None

        try:
            idx = int(raw_match) - 1
        except (TypeError, ValueError):
            logger.warning("LLM returned non-integer match %r for show dir %r", raw_match, show_dir)
            await self._emit("warn", f"LLM show-match returned a non-integer pick for '{show_dir}'")
            return None

        if 0 <= idx < len(shortlist):
            await self._emit(
                "info",
                f"LLM show-match: '{show_dir}' -> '{shortlist[idx].get('name')}'",
                {"show_dir": show_dir, "picked": shortlist[idx].get("name")},
            )
            return shortlist[idx]

        logger.warning("LLM returned out-of-range index %d for show dir %r", idx + 1, show_dir)
        await self._emit("warn", f"LLM show-match returned an out-of-range pick for '{show_dir}'")
        return None

    async def _llm_match(
        self,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Ask the LLM to identify the episode from the filename.

        Only called after all DB-based lookup strategies have failed.

        Args:
            show_id: Database ID of the parent show.
            show_title: Show title for prompt context.
            entry: Parsed entry with the raw file path.

        Returns:
            ``(episode, season, episode_number)`` where ``episode`` is the
            matching :class:`Episode` or None (LLM unavailable, unconfident,
            or its proposed season/episode has no matching DB row), and
            ``season``/``episode_number`` are the values the LLM actually
            proposed — None if it never got far enough to propose any — so
            callers can log what was attempted even on a miss.
        """
        if self.llm is None or not self.llm.is_available():
            return None, None, None

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
            return None, None, None

        ep_list = "\n".join(
            f"S{ep.season_number:02d}E{ep.episode_number:02d}: {ep.name}" for ep in eps[:500]
        )
        filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        prompt = f"Show: {show_title}\nFilename: {filename}\n\nEpisodes:\n{ep_list}"

        try:
            response = await self.llm.complete(
                prompt=prompt,
                system=_LLM_SYSTEM,
                response_format=_LLM_MATCH_RESPONSE_FORMAT,
            )
        except Exception as exc:
            logger.warning("LLM match failed for %r in show %r", filename, show_title)
            await self._emit("warn", f"LLM episode-list match failed for '{filename}': {exc}")
            return None, None, None

        if response is None:
            await self._emit(
                "warn", f"LLM episode-list match returned no response for '{filename}'"
            )
            return None, None, None

        parsed = parse_llm_json(response.content)
        if parsed is None:
            content = response.content
            logger.warning("LLM returned invalid JSON for match of %r: %r", filename, content)
            await self._emit(
                "warn",
                f"LLM episode-list match returned invalid JSON for '{filename}': {content!r}",
            )
            return None, None, None

        if not isinstance(parsed, dict):
            logger.warning(
                "LLM returned non-dict JSON for match of %r: %r", filename, response.content
            )
            await self._emit(
                "warn",
                f"LLM episode-list match returned non-object JSON for '{filename}': "
                f"{response.content!r}",
            )
            return None, None, None

        raw_season = parsed.get("season")
        raw_episode = parsed.get("episode")
        if raw_season is None or raw_episode is None:
            await self._emit(
                "warn", f"LLM episode-list match could not identify '{filename}' among episodes"
            )
            return None, None, None

        try:
            season, episode_num = int(raw_season), int(raw_episode)
        except (TypeError, ValueError):
            logger.warning("LLM returned non-integer S/E for %r: %r", filename, parsed)
            await self._emit(
                "warn",
                f"LLM episode-list match returned non-integer season/episode for '{filename}'",
            )
            return None, None, None

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
            await self._emit(
                "info",
                f"LLM episode-list match: '{filename}' -> S{season:02d}E{episode_num:02d}",
                {"filename": filename, "season": season, "episode": episode_num},
            )
        else:
            await self._emit(
                "warn",
                f"LLM episode-list match proposed S{season:02d}E{episode_num:02d} for "
                f"'{filename}' but no such episode exists in the DB",
                {"filename": filename, "season": season, "episode": episode_num},
            )
        return ep, season, episode_num

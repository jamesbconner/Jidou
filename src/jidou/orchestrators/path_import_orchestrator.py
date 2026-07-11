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

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators.tmdb_orchestrator import TMDBOrchestrator
from jidou.services.episode_group_mapping import resolve_declared_season
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_match_llm import (
    llm_match_episode,
    llm_parse_episode,
    llm_pick_candidate,
)
from jidou.services.episode_tracking import mark_episode_tracked
from jidou.services.filename_parser import parse_filename
from jidou.services.llm_service import LLMService
from jidou.services.path_parser import ParsedPathEntry, group_by_show
from jidou.services.show_lookup import find_show_by_name
from jidou.services.tmdb import TMDBService
from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

logger = logging.getLogger(__name__)

# Strips punctuation (colons, hyphens, apostrophes, etc.) for loose title
# comparison so "Daredevil Born Again" matches TMDB's "Daredevil: Born Again".
_PUNCT = re.compile(r"[^\w\s]")


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
        episodes_tracked: Number of episode rows newly marked ``file_tracked=True``.
        episodes_unmatched: Number of entries with no matching episode row.
        episodes_already_tracked: Number of entries that resolved to an
            Episode row a *different* entry in this same import already
            tracked — e.g. two filenames whose season/episode both resolve
            to the same real episode. Counted separately from both
            ``episodes_tracked`` and ``episodes_unmatched`` so a resolution
            collision is never silently invisible in either counter.
    """

    show_dir: str
    tmdb_id: int | None = None
    tmdb_title: str | None = None
    action: str = "not_found"
    episodes_tracked: int = 0
    episodes_unmatched: int = 0
    episodes_already_tracked: int = 0
    unmatched_paths: list[str] = field(default_factory=list)
    already_tracked_paths: list[str] = field(default_factory=list)


@dataclass
class PathImportResult:
    """Aggregate result of a full path-file import run.

    Attributes:
        shows_processed: Total unique show directories seen.
        shows_created: Shows newly created from TMDB.
        shows_found: Shows that already existed in the DB.
        shows_not_found: Shows that could not be matched to TMDB.
        episodes_tracked: Total episode rows newly marked ``file_tracked=True``.
        episodes_unmatched: Total entries with no matching episode row.
        episodes_already_tracked: Total entries that resolved to an episode
            a different entry in this same import already tracked — see
            :attr:`ShowImportResult.episodes_already_tracked`.
        show_results: Per-show breakdown.
    """

    shows_processed: int = 0
    shows_created: int = 0
    shows_found: int = 0
    shows_not_found: int = 0
    episodes_tracked: int = 0
    episodes_unmatched: int = 0
    episodes_already_tracked: int = 0
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
                result.episodes_already_tracked += show_result.episodes_already_tracked

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

        # A single collision set shared across primary and all secondary
        # groups so that cross-group duplicates (e.g. primary and secondary
        # resolving to the same show via aliases) are visible in the
        # episodes_already_tracked counter rather than silently vanishing.
        shared_episode_ids: set[int] = set()

        results = [
            await self._process_show_entries(
                show_dir, primary_show, action, matched, matched_episode_ids=shared_episode_ids
            )
        ]

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
                    matched_episode_ids=shared_episode_ids,
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
            else:
                # ensure_episode_group_map handles its own exceptions
                # internally, but wrap defensively so a coding error in the
                # method itself never aborts a show resolution.
                try:
                    await TMDBOrchestrator(self.session, self.tmdb).ensure_episode_group_map(show)
                except Exception:
                    logger.warning(
                        "ensure_episode_group_map raised unexpectedly for show id=%d",
                        show.id,
                        exc_info=True,
                    )

        return show, "found"

    async def _process_show_entries(
        self,
        label: str,
        show: Show | None,
        action: str,
        entries: list[ParsedPathEntry],
        set_local_path: bool = True,
        matched_episode_ids: set[int] | None = None,
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
            matched_episode_ids: Shared set of episode IDs already claimed
                by a previous ``_process_show_entries`` call within the same
                ``_import_show`` invocation.  When provided, a collision
                against this set is counted as ``episodes_already_tracked``
                rather than silently falling into a counter gap.  When
                ``None``, a fresh set is created (backwards-compatible for
                any caller that doesn't need cross-group collision detection).

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

        # Match each file entry to an Episode row. Tracks which episode IDs
        # this loop has already claimed so a second file resolving to the
        # same episode (e.g. a season/episode numbering mismatch collision)
        # is never silently invisible in either the tracked or unmatched
        # counters -- see episodes_already_tracked.
        if matched_episode_ids is None:
            matched_episode_ids = set()
        for entry in entries:
            ep, resolved_season, resolved_episode = await self._find_episode(
                show.id, show.title, entry, show.episode_group_map
            )
            if ep is not None and ep.id in matched_episode_ids:
                filename = entry.raw_path.replace("\\", "/").rsplit("/", 1)[-1]
                show_result.episodes_already_tracked += 1
                show_result.already_tracked_paths.append(entry.raw_path)
                await self._emit(
                    "warn",
                    f"'{filename}' resolved to the same episode "
                    f"(S{ep.season_number:02d}E{ep.episode_number:02d}) as another file "
                    "in this import — check for a season/episode numbering mismatch",
                    {
                        "path": entry.raw_path,
                        "episode_id": ep.id,
                        "season": ep.season_number,
                        "episode": ep.episode_number,
                    },
                )
                continue
            if ep is not None:
                matched_episode_ids.add(ep.id)
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

        if show_result.episodes_unmatched or show_result.episodes_already_tracked:
            parts = []
            if show_result.episodes_unmatched:
                parts.append(f"{show_result.episodes_unmatched} unmatched")
            if show_result.episodes_already_tracked:
                parts.append(
                    f"{show_result.episodes_already_tracked} resolved to a duplicate episode"
                )
            await self._emit(
                "warn",
                f"{', '.join(parts)} file(s) for '{show.title}'",
                {
                    "episodes_tracked": show_result.episodes_tracked,
                    "episodes_unmatched": show_result.episodes_unmatched,
                    "episodes_already_tracked": show_result.episodes_already_tracked,
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
        return await find_show_by_name(self.session, name)

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
            llm_pick = await llm_pick_candidate(
                self.llm, show_dir, candidates, on_event=self.on_event
            )
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

    async def _find_episode(
        self,
        show_id: int,
        show_title: str,
        entry: ParsedPathEntry,
        episode_group_map: dict[str, object] | None = None,
    ) -> tuple[Episode | None, int | None, int | None]:
        """Match a parsed path entry to an Episode row.

        Lookup priority:
        1. If regex gave no episode, ask the LLM to parse season/episode from
           the filename alone (lightweight prompt, no episode list needed).
        2. Season + episode DB match (standard S##E## lookup).
        3. On a season>1 miss: episode_groups-based remap — resolves a
           declared season/episode that doesn't exist in TMDB's real
           structure (e.g. a fansub cour-folder for a show TMDB tracks as one
           absolute season) via
           :func:`~jidou.services.episode_group_mapping.resolve_declared_season`.
        4. Absolute episode number column (populated from TMDB episode_groups
           during sync — see :mod:`~jidou.services.episode_group_mapping`).
        5. LLM episode-list match — filename + full episode list sent to the LLM.

        Steps 3-4 are only reachable past step 2's miss; step 4 is also tried
        directly when the entry carries no season at all, using
        ``entry.absolute_candidate`` when set (the raw joined number from an
        ambiguous compact-code guess, e.g. "212" guessed as S02E12) or the
        bare episode number otherwise.

        Args:
            show_id: Database ID of the parent show.
            show_title: Show title for the LLM prompt context.
            entry: Parsed entry describing the file's position.
            episode_group_map: The show's ``episode_group_map`` (from
                :func:`~jidou.services.episode_group_mapping.to_storage_map`),
                or None if never built.

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
            llm_season, llm_episode = await llm_parse_episode(
                self.llm, filename, season, on_event=self.on_event
            )
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
            ep = await resolve_episode(self.session, show_id, season, episode)
            if ep is not None:
                return ep, season, episode
            if season > 1:
                remapped = resolve_declared_season(episode_group_map, season, episode)
                if remapped is not None:
                    real_season, real_episode = remapped
                    remapped_ep = await resolve_episode(
                        self.session, show_id, real_season, real_episode
                    )
                    if remapped_ep is not None:
                        return remapped_ep, real_season, real_episode
                # Before giving up to the LLM, try the absolute-number column —
                # the show's real data may use absolute numbering (or this
                # season/episode pair may itself be an ambiguous compact-code
                # guess whose raw number is the correct absolute episode).
                abs_ep = await resolve_episode(self.session, show_id, None, absolute_guess)
                if abs_ep is not None:
                    return abs_ep, season, episode
                llm_ep, llm_season, llm_episode_num = await llm_match_episode(
                    self.session, self.llm, show_id, show_title, entry, on_event=self.on_event
                )
                return (
                    llm_ep,
                    llm_season if llm_season is not None else season,
                    llm_episode_num if llm_episode_num is not None else episode,
                )
            # Season 1 directory: the episode number may still be a continuous
            # absolute count (e.g. a show with all 148 episodes in Season 01).
            # Fall through to the absolute-number lookup before the LLM.

        # No season info — this is an absolute episode number.
        abs_ep = await resolve_episode(self.session, show_id, None, absolute_guess)
        if abs_ep is not None:
            return abs_ep, season, episode

        llm_ep, llm_season, llm_episode_num = await llm_match_episode(
            self.session, self.llm, show_id, show_title, entry, on_event=self.on_event
        )
        return (
            llm_ep,
            llm_season if llm_season is not None else season,
            llm_episode_num if llm_episode_num is not None else episode,
        )

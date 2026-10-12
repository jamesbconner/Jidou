"""Orchestrator for routing MATCHED files from staging to their final local paths."""

import logging
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.episode import Episode
from jidou.models.show import Show
from jidou.orchestrators._events import EventSink
from jidou.services.callbacks import OnEvent, OnProgress
from jidou.services.episode_lookup import resolve_episode
from jidou.services.episode_tracking import dismiss_orphans_for_file, mark_episode_tracked
from jidou.services.path_transport import decode_path_bytes

logger = logging.getLogger(__name__)

_SEASON_DIR_RE = re.compile(r"^Season\s+(\d+)$")


def _season_dir_name(show_dir: Path, season: int) -> str:
    """Determine the season directory name to use, honouring an existing convention.

    Some shows have season directories named "Season #" (no zero-padding)
    rather than the default "Season ##" — a mix that can happen when a show
    was seeded or imported before this convention was adopted, or just
    matches how the source distributed it. This is only ambiguous for
    single-digit seasons (2 digits and up look identical either way), so:

    1. If a directory for *this exact season* already exists, in either
       format, reuse it — a season already in progress must never get a
       second, differently-formatted directory partway through.
    2. Otherwise, infer the convention from the show's other single-digit
       season directories, so a show with "Season 1"/"Season 2" gets
       "Season 3" for newly arrived episodes instead of "Season 03".
    3. Default to zero-padded "Season NN" when there is no existing
       directory to reuse and no convention to infer (new show, or only
       double-digit seasons present so far).

    Args:
        show_dir: The show's root directory on the local filesystem.
        season: The season number being routed.

    Returns:
        The directory name to use, e.g. ``"Season 03"`` or ``"Season 3"``.
    """
    padded = f"Season {season:02d}"
    unpadded = f"Season {season}"

    if season < 10 and (show_dir / unpadded).is_dir():
        return unpadded
    if (show_dir / padded).is_dir():
        return padded

    try:
        entries = [p.name for p in show_dir.iterdir() if p.is_dir()]
    except OSError:
        entries = []

    saw_unpadded = False
    saw_padded = False
    for name in entries:
        match = _SEASON_DIR_RE.match(name)
        if not match:
            continue
        num_str = match.group(1)
        if int(num_str) >= 10:
            continue  # Same spelling either way — not informative.
        if len(num_str) == 1:
            saw_unpadded = True
        elif num_str.startswith("0"):
            saw_padded = True

    return unpadded if saw_unpadded and not saw_padded else padded


def _final_path_for(
    show_local_path: str,
    season: int | None,
    filename: str,
    is_movie: bool = False,
) -> Path:
    """Compute the final routed path for a MATCHED file.

    TV/anime episodes land in ``show_local_path/Season NN/filename`` (or
    ``Season N`` when that's the convention already established for this
    show — see :func:`_season_dir_name`). Movies land directly in
    ``show_local_path/filename``. Files with no season number are placed at
    the show root.

    Args:
        show_local_path: Root directory for the show on the local filesystem.
        season: Season number, or None for movies or unidentified season.
        filename: The bare filename (no directory component).
        is_movie: Whether this file is a movie (skips season directory).

    Returns:
        Absolute :class:`Path` for the final destination.
    """
    base = Path(show_local_path)
    if is_movie or season is None:
        return base / filename
    return base / _season_dir_name(base, season) / filename


@dataclass
class RouteResult:
    """Result of a batch file-routing operation."""

    files_routed: int
    files_failed: int
    dry_run: bool


class RouteOutcome(Enum):
    """How routing one file ended, as tallied by :meth:`RouteOrchestrator.run`."""

    ROUTED = auto()  # moved, already in place, or (dry run) would be routed
    FAILED = auto()
    SKIPPED_NO_COMMIT = auto()  # dry-run skip: counted nowhere, nothing committed


def _unique_destination(dest: Path, current_local_path: str | None) -> Path:
    """Return a destination that will not overwrite a different existing file.

    If *dest* is occupied by a file other than the one being routed, a numeric
    suffix (``name.1.ext``, ``name.2.ext``, ...) is added until the path is free.

    Args:
        dest: The preferred destination path.
        current_local_path: The file's current ``local_path``. When it already
            equals *dest* the file is its own occupant and *dest* is returned
            unchanged.

    Returns:
        *dest* itself, or the first free suffixed sibling of it.
    """
    if not dest.exists() or str(current_local_path) == str(dest):
        return dest
    counter = 1
    candidate = dest
    while candidate.exists():
        candidate = dest.parent / f"{dest.stem}.{counter}{dest.suffix}"
        counter += 1
    return candidate


class RouteOrchestrator:
    """Move MATCHED files from the staging area to their final local paths.

    Each file's destination is computed from ``show.local_path``,
    ``file.parsed_season``, and ``file.original_filename``.

    Args:
        session: Active async SQLAlchemy session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _update_episode_tracking(self, file: DownloadedFile, show_id: int) -> None:
        """Set the routed file's episode as tracked.

        For manually-matched files (``episode_id=None`` after the match
        endpoint clears it) we resolve the episode by parsed season/episode
        numbers and write back ``file.episode_id``.

        Args:
            file: The just-routed DownloadedFile (episode_id may be None).
            show_id: Show to search within when resolving by parsed numbers.
        """
        if file.episode_id is not None:
            ep = await self.session.get(Episode, file.episode_id)
        elif file.parsed_episode is not None:
            # Covers both regular TV (season + episode known) and anime
            # (season=None -> absolute_episode_number, then Season-1 fallback).
            ep = await resolve_episode(
                self.session, show_id, file.parsed_season, file.parsed_episode
            )
            if ep is not None:
                file.episode_id = ep.id
                await dismiss_orphans_for_file(self.session, file.id)
        else:
            ep = None

        if ep is None:
            logger.warning(
                "Cannot track episode for file id=%d (%r): "
                "episode_id=%s parsed_season=%s parsed_episode=%s — "
                "no matching episode row found (show_id=%d)",
                file.id,
                file.original_filename,
                file.episode_id,
                file.parsed_season,
                file.parsed_episode,
                show_id,
            )
            return

        # local_path is already the final routed path by this point (set by
        # _mark_routed() before this is called) — falling back to
        # original_filename only covers the case where routing left it unset.
        mark_episode_tracked(ep, file.local_path or file.original_filename, "match")

    async def _effective_season(self, file: DownloadedFile, *, is_movie: bool) -> int | None:
        """Return the season used to pick the destination directory.

        For anime parsed without a season (``parsed_season=None``), the
        ParseOrchestrator now backfills ``parsed_season`` from the resolved
        episode. For files that were matched before that fix, recover the season
        from the episode row here so the file doesn't land at the show root.

        Args:
            file: The file being routed.
            is_movie: Whether the show is a movie (movies never use a season).

        Returns:
            The season number, or None when there is none to use.
        """
        if file.parsed_season is not None or is_movie or file.episode_id is None:
            return file.parsed_season
        ep = await self.session.get(Episode, file.episode_id)
        return ep.season_number if ep is not None else None

    async def _mark_routed(self, file: DownloadedFile, dest: Path | None, show_id: int) -> None:
        """Record a successful route and set the episode as tracked.

        Args:
            file: The routed file.
            dest: Final path to store as ``local_path``. ``None`` leaves
                ``local_path`` as it is (the file was already at its destination).
            show_id: Show to search within when resolving the episode.
        """
        if dest is not None:
            file.local_path = str(dest)
        file.status = FileStatus.ROUTED
        file.error_message = None
        await self._update_episode_tracking(file, show_id)

    async def _skip_without_local_path(
        self, file: DownloadedFile, show: Show, *, dry_run: bool, sink: EventSink
    ) -> RouteOutcome:
        """Handle a file whose show has no ``local_path`` configured.

        Args:
            file: The file that cannot be routed.
            show: Its show.
            dry_run: When True nothing is written or committed.
            sink: Event sink for the skip warning.

        Returns:
            ``FAILED`` after committing ``ERROR`` in a real run, otherwise
            ``SKIPPED_NO_COMMIT``.
        """
        logger.warning(
            "Show id=%d has no local_path; cannot route file id=%d",
            show.id,
            file.id,
        )
        await sink(
            "warn",
            f"Skipped {file.original_filename!r}: show {show.title!r} has no local path configured",
            {"file_id": file.id, "show_id": show.id},
        )
        if dry_run:
            return RouteOutcome.SKIPPED_NO_COMMIT
        file.status = FileStatus.ERROR
        file.error_message = "Show has no local_path configured"
        await self.session.flush()
        await self.session.commit()
        return RouteOutcome.FAILED

    async def _complete_prior_move(
        self,
        file: DownloadedFile,
        show: Show,
        source: Path,
        dest: Path,
        sink: EventSink,
    ) -> bool:
        """Finish a ROUTING retry whose move completed but whose commit did not.

        If the source is already gone but the dest exists, record ROUTED and
        commit; the caller must then skip its own closing flush/commit.

        Args:
            file: The file being routed.
            show: Its show.
            source: Decoded staging path.
            dest: Computed destination.
            sink: Event sink.

        Returns:
            True when the retry was completed (and committed) here, False when
            this is not a retry and normal routing should continue.

        Raises:
            FileNotFoundError: The destination exists but its size does not match
                the tracked file, so it is not assumed to be our own prior move.
        """
        if source.exists() or not dest.exists() or str(file.local_path) == str(dest):
            return False
        # Verify dest actually holds *this* file's content before
        # accepting "my own prior move must have succeeded" —
        # otherwise a genuine destination collision landing
        # exactly when a retry is in flight would misattribute
        # someone else's file to this DB row. file_size == 0 means
        # "unknown" (e.g. legacy rows predating this field) and
        # skips the check, matching the prior, unverified behavior.
        if file.file_size and dest.stat().st_size != file.file_size:
            raise FileNotFoundError(
                f"Staging file not found: {source} (destination {dest} "
                "exists but its size does not match the tracked file, "
                "so this is not assumed to be our own prior move)"
            )
        logger.warning(
            "Retry: staging gone but dest exists for file id=%d; marking ROUTED",
            file.id,
        )
        await sink(
            "info",
            f"Already routed (retry): {file.original_filename!r} → {dest}",
            {"file_id": file.id, "dest": str(dest)},
        )
        await self._mark_routed(file, dest, show.id)
        await self.session.flush()
        await self.session.commit()
        return True

    async def _move_to_destination(
        self, file: DownloadedFile, show: Show, source: Path, dest: Path, sink: EventSink
    ) -> None:
        """Move *source* to *dest*, tolerating a copy that cannot delete the original.

        Args:
            file: The file being routed.
            show: Its show (for event context).
            source: Decoded staging path.
            dest: Final destination path.
            sink: Event sink.

        Raises:
            OSError: The move failed and *dest* does not hold a full copy of *source*.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(dest))
        except OSError as move_exc:
            # shutil.move falls back to copy-then-delete when a fast
            # rename isn't possible (e.g. correcting a mis-routed
            # file already on the NAS). Some NAS accounts are
            # deliberately granted no delete permission to prevent
            # a catastrophic accidental wipe, so the copy can
            # succeed while the cleanup delete of the original
            # fails. Detect that specific case (dest now holds a
            # full copy of source) and treat it as a successful
            # route with a warning, rather than failing the file
            # and leaving it stuck as MATCHED/ERROR forever.
            if not (
                dest.exists() and source.exists() and dest.stat().st_size == source.stat().st_size
            ):
                raise
            logger.warning(
                "Routed %s → %s, but could not remove the original "
                "(likely no delete permission on the source share): %s",
                source,
                dest,
                move_exc,
            )
            await sink(
                "warn",
                f"Routed {file.original_filename!r} → {dest}, but could not "
                f"delete the original at {source} ({move_exc}). "
                f"Remove it manually to reclaim space.",
                {
                    "file_id": file.id,
                    "show": show.title,
                    "dest": str(dest),
                    "leftover_source": str(source),
                },
            )
        else:
            logger.info("Routed %s → %s", source, dest)
            await sink(
                "info",
                f"Routed {file.original_filename!r} → {dest}",
                {"file_id": file.id, "show": show.title, "dest": str(dest)},
            )

    async def _place_file(
        self, file: DownloadedFile, show: Show, source: Path, dest: Path, sink: EventSink
    ) -> None:
        """Put *source* at *dest* (or a collision-free sibling) and mark it routed.

        Args:
            file: The file being routed.
            show: Its show.
            source: Decoded staging path.
            dest: Computed destination.
            sink: Event sink.

        Raises:
            FileNotFoundError: The staging file does not exist.
            OSError: The move failed unrecoverably.
        """
        if not source.exists():
            raise FileNotFoundError(f"Staging file not found: {source}")

        # Resolve basename collision: if dest is already occupied by a
        # *different* file, add a numeric suffix rather than overwriting.
        unique = _unique_destination(dest, file.local_path)
        if unique != dest:
            dest = unique
            logger.warning(
                "Destination collision for file id=%d; writing to %s instead",
                file.id,
                dest,
            )

        # Synthetic import files already live at their final path —
        # skip the move to avoid shutil.Error(src == dst).
        if str(source) == str(dest):
            logger.info(
                "File id=%d already at destination; no move needed: %s",
                file.id,
                dest,
            )
            await sink(
                "info",
                f"Already at destination: {file.original_filename!r}",
                {"file_id": file.id, "dest": str(dest)},
            )
            await self._mark_routed(file, None, show.id)
            return

        await self._move_to_destination(file, show, source, dest, sink)
        # Only point local_path at dest once the move (or the NAS
        # copy-then-failed-delete fallback) has actually happened.
        # Writing this before the move and then crashing before
        # shutil.move runs would durably orphan the file: the DB
        # would say it's at dest while the file is still sitting
        # untouched at the old staging path, with no durable record
        # of where it really is. A crash *after* the move but before
        # the commit is still recovered by the ROUTING-retry branch
        # (_complete_prior_move) on the next run.
        await self._mark_routed(file, dest, show.id)

    async def _route_one(
        self, file: DownloadedFile, show: Show, *, dry_run: bool, sink: EventSink
    ) -> RouteOutcome:
        """Route a single file, owning its per-file flush/commit.

        Args:
            file: The MATCHED/ROUTING file.
            show: Its show.
            dry_run: Plan and log only; no status change, move or commit.
            sink: Event sink.

        Returns:
            How the file ended; a dry-run plan counts as ``ROUTED``.
        """
        if show.local_path is None:
            return await self._skip_without_local_path(file, show, dry_run=dry_run, sink=sink)

        is_movie = (show.content_type or show.media_type) == "movie"
        effective_season = await self._effective_season(file, is_movie=is_movie)
        dest = _final_path_for(
            show.local_path,
            effective_season,
            file.original_filename,
            is_movie=is_movie,
        )

        if dry_run:
            logger.info(
                "[DRY RUN] Would route %s → %s",
                file.local_path or file.original_filename,
                dest,
            )
            await sink(
                "info",
                f"[Dry run] Would route {file.original_filename!r} → {dest}",
                {"file_id": file.id, "dest": str(dest)},
            )
            return RouteOutcome.ROUTED

        file.status = FileStatus.ROUTING
        await self.session.flush()
        await self.session.commit()

        staging_path: str | None = file.local_path
        outcome = RouteOutcome.ROUTED
        try:
            if file.local_path is None:
                raise FileNotFoundError(f"File id={file.id} has no local_path in staging")

            # local_path may be percent-encoded (see path_transport) if it
            # was ever written by a code path that stores the JSON/DB-safe
            # encoded form — decode back to the real bytes before touching
            # the filesystem. A no-op for the plain paths this orchestrator
            # normally sees.
            source = Path(decode_path_bytes(file.local_path))

            # A completed retry has already committed; skip the closing commit.
            if await self._complete_prior_move(file, show, source, dest, sink):
                return RouteOutcome.ROUTED
            await self._place_file(file, show, source, dest, sink)
        except Exception as exc:
            logger.error(
                "Failed to route file id=%d (%s): %s",
                file.id,
                file.original_filename,
                exc,
            )
            await sink(
                "error",
                f"Failed to route {file.original_filename!r}: {exc}",
                {"file_id": file.id, "error": str(exc)},
            )
            # Reset local_path to the original staging path so a future retry
            # can still locate the source file.
            file.local_path = staging_path
            file.status = FileStatus.ERROR
            file.error_message = str(exc)
            outcome = RouteOutcome.FAILED

        await self.session.flush()
        await self.session.commit()
        return outcome

    async def run(
        self,
        dry_run: bool = False,
        on_progress: OnProgress | None = None,
        on_event: OnEvent | None = None,
    ) -> RouteResult:
        """Route all MATCHED files to their final locations.

        Transitions: MATCHED → ROUTING → ROUTED (or ERROR on failure).
        The staging file is moved (not copied) so disk space is reclaimed. If
        the destination filesystem allows writes but not deletes (e.g. a
        deliberately delete-restricted NAS account), a copy that succeeds but
        fails to remove the original is still treated as ROUTED, with a
        warning logged instead of an error — see ``_move_to_destination()``.

        Args:
            dry_run: Log what would happen without moving any files.
            on_progress: Optional async callback(current, total, message).
            on_event: Optional async callback(level, message, ctx) for
                structured per-file event log entries.

        Returns:
            RouteResult with counts.
        """

        sink = EventSink(on_event, swallow_errors=True)

        stmt = (
            select(DownloadedFile, Show)
            .join(Show, DownloadedFile.show_id == Show.id)
            .where(DownloadedFile.status.in_([FileStatus.MATCHED, FileStatus.ROUTING]))
        )
        rows = list((await self.session.execute(stmt)).all())
        total = len(rows)

        counts: Counter[RouteOutcome] = Counter()
        for idx, (file, show) in enumerate(rows, 1):
            if on_progress:
                await on_progress(idx, total, f"Routing {file.original_filename}")
            counts[await self._route_one(file, show, dry_run=dry_run, sink=sink)] += 1

        files_routed = counts[RouteOutcome.ROUTED]
        files_failed = counts[RouteOutcome.FAILED]
        if dry_run:
            logger.info(
                "Route dry-run complete: %d would be routed (dry_run=True)",
                files_routed,
            )
        else:
            logger.info("Route complete: %d routed, %d failed", files_routed, files_failed)

        return RouteResult(
            files_routed=files_routed,
            files_failed=files_failed,
            dry_run=dry_run,
        )

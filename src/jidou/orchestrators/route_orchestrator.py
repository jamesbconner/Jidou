"""Orchestrator for routing MATCHED files from staging to their final local paths."""

import logging
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.models.show import Show

logger = logging.getLogger(__name__)


def _final_path_for(
    show_local_path: str,
    season: int | None,
    filename: str,
    is_movie: bool = False,
) -> Path:
    """Compute the final routed path for a MATCHED file.

    TV/anime episodes land in ``show_local_path/Season NN/filename``.
    Movies land directly in ``show_local_path/filename``.
    Files with no season number are placed at the show root.

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
    return base / f"Season {season:02d}" / filename


@dataclass
class RouteResult:
    """Result of a batch file-routing operation."""

    files_routed: int
    files_failed: int
    dry_run: bool


class RouteOrchestrator:
    """Move MATCHED files from the staging area to their final local paths.

    Each file's destination is computed from ``show.local_path``,
    ``file.parsed_season``, and ``file.original_filename``.

    Args:
        session: Active async SQLAlchemy session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        dry_run: bool = False,
        on_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> RouteResult:
        """Route all MATCHED files to their final locations.

        Transitions: MATCHED → ROUTING → ROUTED (or ERROR on failure).
        The staging file is moved (not copied) so disk space is reclaimed.

        Args:
            dry_run: Log what would happen without moving any files.
            on_progress: Optional async callback(current, total, message).

        Returns:
            RouteResult with counts.
        """
        stmt = (
            select(DownloadedFile, Show)
            .join(Show, DownloadedFile.show_id == Show.id)
            .where(DownloadedFile.status.in_([FileStatus.MATCHED, FileStatus.ROUTING]))
        )
        rows = list((await self.session.execute(stmt)).all())
        total = len(rows)

        files_routed = 0
        files_failed = 0

        for idx, (file, show) in enumerate(rows, 1):
            if on_progress:
                await on_progress(idx, total, f"Routing {file.original_filename}")

            if show.local_path is None:
                logger.warning(
                    "Show id=%d has no local_path; cannot route file id=%d",
                    show.id,
                    file.id,
                )
                if not dry_run:
                    file.status = FileStatus.ERROR
                    file.error_message = "Show has no local_path configured"
                    files_failed += 1
                    await self.session.flush()
                    await self.session.commit()
                continue

            is_movie = (show.content_type or show.media_type) == "movie"
            dest = _final_path_for(
                show.local_path,
                file.parsed_season,
                file.original_filename,
                is_movie=is_movie,
            )

            if dry_run:
                logger.info(
                    "[DRY RUN] Would route %s → %s",
                    file.local_path or file.original_filename,
                    dest,
                )
                files_routed += 1
                continue

            if not dry_run:
                file.status = FileStatus.ROUTING
                await self.session.flush()
                await self.session.commit()

            staging_path: str | None = file.local_path
            try:
                if file.local_path is None:
                    raise FileNotFoundError(f"File id={file.id} has no local_path in staging")

                source = Path(file.local_path)

                # Handle ROUTING retry: if the source is already gone but the
                # dest exists, the move completed but the commit didn't — just
                # record ROUTED and move on.
                if not source.exists() and dest.exists() and str(file.local_path) != str(dest):
                    logger.warning(
                        "Retry: staging gone but dest exists for file id=%d; marking ROUTED",
                        file.id,
                    )
                    file.local_path = str(dest)
                    file.status = FileStatus.ROUTED
                    file.error_message = None
                    files_routed += 1
                    await self.session.flush()
                    await self.session.commit()
                    continue

                if not source.exists():
                    raise FileNotFoundError(f"Staging file not found: {source}")

                # Resolve basename collision: if dest is already occupied by a
                # *different* file, add a numeric suffix rather than overwriting.
                if dest.exists() and str(file.local_path) != str(dest):
                    stem = dest.stem
                    suffix = dest.suffix
                    parent = dest.parent
                    counter = 1
                    while dest.exists():
                        dest = parent / f"{stem}.{counter}{suffix}"
                        counter += 1
                    logger.warning(
                        "Destination collision for file id=%d; writing to %s instead",
                        file.id,
                        dest,
                    )

                dest.parent.mkdir(parents=True, exist_ok=True)

                # Write dest to DB *before* the filesystem move so a crash after
                # the move still leaves the row pointing at the correct location.
                file.local_path = str(dest)
                await self.session.flush()
                await self.session.commit()

                shutil.move(str(source), str(dest))

                file.status = FileStatus.ROUTED
                file.error_message = None
                files_routed += 1
                logger.info("Routed %s → %s", source, dest)

            except Exception as exc:
                logger.error(
                    "Failed to route file id=%d (%s): %s",
                    file.id,
                    file.original_filename,
                    exc,
                )
                # Reset local_path to the original staging path so a future retry
                # can still locate the source file.
                file.local_path = staging_path
                file.status = FileStatus.ERROR
                file.error_message = str(exc)
                files_failed += 1

            await self.session.flush()
            await self.session.commit()

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

"""Create display-only DownloadedFile rows for files already at their final path.

Shared by bulk path-import (:class:`PathImportOrchestrator`) and manual
episode-to-file linking (``POST /shows/{show_id}/episodes/{episode_id}/link-file``)
— both cases record a file that was never downloaded or routed by Jidou itself,
only linked after the fact.
"""

from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.path_transport import basename_any, decode_path_bytes_for_display

logger = logging.getLogger(__name__)

# The ``remote_path`` prefix marking a file that was linked after the fact rather
# than downloaded; code that matches or builds such paths must use the helpers below.
SYNTHETIC_IMPORT_SCHEME: Final = "synthetic-import://"


def synthetic_remote_path(path: str) -> str:
    """Build the ``remote_path`` that records *path* as a synthetic import.

    Args:
        path: The file's on-disk path (or bare filename for episode lookups).

    Returns:
        ``SYNTHETIC_IMPORT_SCHEME`` followed by *path*.
    """
    return f"{SYNTHETIC_IMPORT_SCHEME}{path}"


def is_synthetic_remote_path(remote_path: str) -> bool:
    """Return whether *remote_path* belongs to a synthetic import row.

    Args:
        remote_path: A ``DownloadedFile.remote_path`` value.

    Returns:
        True when it starts with ``SYNTHETIC_IMPORT_SCHEME``.
    """
    return remote_path.startswith(SYNTHETIC_IMPORT_SCHEME)


async def create_synthetic_import_file(
    session: AsyncSession,
    show_id: int,
    episode_id: int | None,
    raw_path: str,
    *,
    parsed_season: int | None = None,
    parsed_episode: int | None = None,
) -> DownloadedFile | None:
    """Create a display-only, already-ROUTED DownloadedFile for a file at its final path.

    The file is already at its final library location — it was never downloaded
    or routed by Jidou itself — so this row exists purely to make it show up
    correctly on the Files page. It uses the ``synthetic-import://`` ``remote_path``
    convention recognised elsewhere: the episode-listing query excludes these rows
    from the backing-files list (so Fix Match's "Imported" chip is unaffected), and
    RouteOrchestrator already no-ops a move when source equals destination.

    Reassignment for episodes tracked this way goes through the ``assign-import``
    endpoint, not ``begin-rematch`` — this row never participates in the
    match/route pipeline.

    Args:
        session: Active async DB session.
        show_id: Database ID of the parent show.
        episode_id: Database ID of the matched episode, or ``None`` for a
            movie — movies have no ``Episode`` rows, so the file is linked
            to the show alone (see ``POST /shows/{show_id}/link-movie-file``).
        raw_path: The file's existing absolute path (already at its final
            on-disk location).
        parsed_season: The matched episode's season number, or ``None`` for
            a movie. Populated so a later show-rematch's orphan-relink pass
            (see ``ShowRematchOrchestrator._restore_tracking_and_relink``)
            can find this row after episodes are purged and re-synced from
            TMDB — without it the file is silently excluded from relinking.
        parsed_episode: The matched episode's episode number, or ``None``
            for a movie.

    Returns:
        The created (or pre-existing) :class:`DownloadedFile`, or ``None`` if
        a concurrent request won the race to create it.
    """
    remote_path = synthetic_remote_path(raw_path)
    existing_stmt = select(DownloadedFile).where(DownloadedFile.remote_path == remote_path)
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    # original_filename is display-only (never echoed back for a lookup, unlike
    # local_path/remote_path below), so store the human-readable decoded form
    # directly rather than leaking raw_path's percent-encoding into the UI.
    filename = basename_any(decode_path_bytes_for_display(raw_path))
    record = DownloadedFile(
        show_id=show_id,
        episode_id=episode_id,
        original_filename=filename,
        remote_path=remote_path,
        local_path=raw_path,
        status=FileStatus.ROUTED,
        parsed_season=parsed_season,
        parsed_episode=parsed_episode,
    )
    try:
        async with session.begin_nested():
            session.add(record)
    except IntegrityError:
        logger.debug("Synthetic file record already exists (race): %s", raw_path)
        return None
    return record

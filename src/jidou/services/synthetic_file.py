"""Create display-only DownloadedFile rows for files already at their final path.

Shared by bulk path-import (:class:`PathImportOrchestrator`) and manual
episode-to-file linking (``POST /shows/{show_id}/episodes/{episode_id}/link-file``)
— both cases record a file that was never downloaded or routed by Jidou itself,
only linked after the fact.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus

logger = logging.getLogger(__name__)


async def create_synthetic_import_file(
    session: AsyncSession,
    show_id: int,
    episode_id: int,
    raw_path: str,
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
        episode_id: Database ID of the matched episode.
        raw_path: The file's existing absolute path (already at its final
            on-disk location).

    Returns:
        The created (or pre-existing) :class:`DownloadedFile`, or ``None`` if
        a concurrent request won the race to create it.
    """
    synthetic_remote_path = f"synthetic-import://{raw_path}"
    existing_stmt = select(DownloadedFile).where(
        DownloadedFile.remote_path == synthetic_remote_path
    )
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    filename = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
    record = DownloadedFile(
        show_id=show_id,
        episode_id=episode_id,
        original_filename=filename,
        remote_path=synthetic_remote_path,
        local_path=raw_path,
        status=FileStatus.ROUTED,
    )
    try:
        async with session.begin_nested():
            session.add(record)
    except IntegrityError:
        logger.debug("Synthetic file record already exists (race): %s", raw_path)
        return None
    return record

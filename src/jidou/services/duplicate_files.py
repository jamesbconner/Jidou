"""Find the file an episode already has, so a second copy can be flagged (decision D33)."""

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile, FileStatus
from jidou.services.synthetic_file import SYNTHETIC_IMPORT_SCHEME

# Statuses in which a file counts as already covering its episode: matched and
# on its way to (or already in) the library.
SETTLED_STATUSES: Final = (FileStatus.MATCHED, FileStatus.ROUTING, FileStatus.ROUTED)


async def find_duplicate_original(
    session: AsyncSession, *, episode_id: int, file_id: int
) -> DownloadedFile | None:
    """Return the file that already covers *episode_id*, other than *file_id*.

    Only real downloads count: synthetic-import rows (``remote_path`` under
    ``SYNTHETIC_IMPORT_SCHEME``) record a file that was imported in place, not
    a second copy, so they are skipped. The file itself is excluded so a
    re-parse against its own earlier link never flags it as its own
    duplicate. When several files qualify, the lowest id (the earliest row)
    is returned, so the choice is deterministic.

    Args:
        session: Active async SQLAlchemy session.
        episode_id: The episode the file is being linked to.
        file_id: The file being linked (excluded from the search).

    Returns:
        The earliest other non-synthetic MATCHED/ROUTING/ROUTED file linked
        to the episode, or None.
    """
    stmt = (
        select(DownloadedFile)
        .where(
            DownloadedFile.episode_id == episode_id,
            DownloadedFile.status.in_(SETTLED_STATUSES),
            DownloadedFile.id != file_id,
            ~DownloadedFile.remote_path.like(f"{SYNTHETIC_IMPORT_SCHEME}%"),
        )
        .order_by(DownloadedFile.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()

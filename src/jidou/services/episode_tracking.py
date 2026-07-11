"""Helpers for setting and clearing episode tracking state.

The four tracking fields (``file_tracked``, ``file_tracked_at``,
``tracked_filename``, ``tracked_source``) always move together.  These
helpers are the single source of truth so that adding a new field only
requires a change here.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord

# Sentinel distinguishing "caller passed None" from "caller omitted tracked_at".
# Needed because a snapshot can have file_tracked_at = NULL, which must be
# restored as NULL rather than overwritten with datetime.now(UTC).
_UNSET: object = object()


def mark_episode_tracked(
    ep: Episode,
    filename: str | None,
    source: str | None,
    tracked_at: datetime | None = _UNSET,  # type: ignore[assignment]
) -> None:
    """Mark *ep* as tracked by a specific file.

    Args:
        ep: Episode ORM object to mutate in place.
        filename: Path or name of the file that tracks this episode.
            May be ``None`` when restoring from a snapshot that had no filename.
        source: Origin of the tracking event (``"match"``, ``"import"``, etc.).
            May be ``None`` when restoring an orphan record that had no source.
        tracked_at: Explicit timestamp for ``file_tracked_at``.  Omit (or do
            not pass the keyword) to use ``datetime.now(UTC)``.  Pass ``None``
            to restore a snapshot that had a NULL timestamp — this is distinct
            from omitting the argument.
    """
    ep.file_tracked = True
    ep.file_tracked_at = datetime.now(UTC) if tracked_at is _UNSET else tracked_at
    ep.tracked_filename = filename
    ep.tracked_source = source


def clear_episode_tracking(ep: Episode) -> None:
    """Clear all tracking state from *ep*.

    Args:
        ep: Episode ORM object to mutate in place.
    """
    ep.file_tracked = False
    ep.file_tracked_at = None
    ep.tracked_filename = None
    ep.tracked_source = None


async def clear_if_unreferenced(
    session: AsyncSession,
    old_episode_id: int | None,
    new_episode_id: int | None,
) -> None:
    """Clear tracking on ``old_episode_id`` if it changed and no file still points to it.

    A file being relinked to a new episode must not blindly clear the episode
    it left behind — another ``DownloadedFile`` row may still reference it.

    Args:
        session: Active async DB session.
        old_episode_id: ``Episode.id`` the file was previously linked to, or ``None``.
        new_episode_id: ``Episode.id`` the file is now linked to, or ``None``.
    """
    if old_episode_id is None or old_episode_id == new_episode_id:
        return
    count_result = await session.execute(
        select(func.count()).where(DownloadedFile.episode_id == old_episode_id)
    )
    if (count_result.scalar() or 0) != 0:
        return
    old_ep = (
        await session.execute(select(Episode).where(Episode.id == old_episode_id))
    ).scalar_one_or_none()
    if old_ep is not None:
        clear_episode_tracking(old_ep)


async def dismiss_orphans_for_file(session: AsyncSession, file_id: int) -> None:
    """Delete any ``OrphanedTrackingRecord`` rows tied to ``file_id``.

    Args:
        session: Active async DB session.
        file_id: ``DownloadedFile.id`` whose orphan records should be dismissed.
    """
    await session.execute(
        OrphanedTrackingRecord.__table__.delete().where(  # type: ignore[attr-defined]
            OrphanedTrackingRecord.downloaded_file_id == file_id
        )
    )

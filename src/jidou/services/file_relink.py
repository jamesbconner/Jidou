"""Operator-driven reassignment of a DownloadedFile's show and episode links.

Extracted from ``PATCH /api/files/{id}`` so the linking invariants (episode
must belong to the file's show; an episode is tracked by at most one file;
stale tracking is cleared only when unreferenced) live in one tested place.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.episode import Episode
from jidou.services.episode_tracking import (
    clear_if_unreferenced,
    dismiss_orphans_for_file,
    mark_episode_tracked,
)


class FileRelinkError(Exception):
    """Base class for rejected file relink operations."""


class EpisodeShowMismatchError(FileRelinkError):
    """The target episode belongs to a different show than the file."""


class EpisodeAlreadyTrackedError(FileRelinkError):
    """The target episode is already tracked by another file."""


async def reassign_show(
    session: AsyncSession,
    file: DownloadedFile,
    new_show_id: int | None,
    *,
    keep_episode: bool,
    keep_error: bool,
) -> None:
    """Point *file* at *new_show_id*, clearing state that belonged to the old show.

    No-op when the show is unchanged. On change: the matcher is cleared, orphan
    records for the file are dismissed (resolving them later would corrupt
    ``show_id``), and the episode link / error message are cleared unless the
    caller is setting them explicitly in the same operation. When the episode
    link is dropped, the old episode's tracking is cleared if no other file
    still references it.

    Args:
        session: Active async DB session.
        file: File to mutate in place.
        new_show_id: Target show id (may be None).
        keep_episode: True when the caller also sets ``episode_id`` explicitly.
        keep_error: True when the caller also sets ``error_message`` explicitly.
    """
    if file.show_id == new_show_id:
        return
    old_episode_id = file.episode_id
    file.show_id = new_show_id
    if not keep_episode:
        file.episode_id = None
    file.matched_by = None
    if not keep_error:
        file.error_message = None
    await dismiss_orphans_for_file(session, file.id)
    if not keep_episode:
        # Must run after the link is nulled: the reference count autoflushes, and
        # a still-linked file would count itself and keep the stale tracking.
        await clear_if_unreferenced(session, old_episode_id, None)


async def relink_episode(
    session: AsyncSession, file: DownloadedFile, new_episode_id: int | None
) -> None:
    """Link *file* to *new_episode_id* (or unlink it) and maintain tracking state.

    Args:
        session: Active async DB session.
        file: File to mutate in place.
        new_episode_id: Target episode id, or None to unlink.

    Raises:
        EpisodeShowMismatchError: The episode belongs to another show.
        EpisodeAlreadyTrackedError: The episode is tracked by a different file.
    """
    old_episode_id = file.episode_id
    file.episode_id = new_episode_id
    if new_episode_id is None:
        file.parsed_season = None
        file.parsed_episode = None
    else:
        # Any orphan record waiting for this file to be re-linked is now resolved.
        await dismiss_orphans_for_file(session, file.id)
        ep = (
            await session.execute(select(Episode).where(Episode.id == new_episode_id))
        ).scalar_one_or_none()
        if ep is not None:
            _ensure_linkable(file, ep, old_episode_id, new_episode_id)
            mark_episode_tracked(ep, file.local_path or file.original_filename, "match")
            file.parsed_season = ep.season_number
            file.parsed_episode = ep.episode_number
    # Clear the previous episode's tracking only when no other file still points to it.
    await clear_if_unreferenced(session, old_episode_id, new_episode_id)


def _ensure_linkable(
    file: DownloadedFile, ep: Episode, old_episode_id: int | None, new_episode_id: int
) -> None:
    """Raise if *ep* may not be linked to *file*.

    The "already tracked" check compares ids rather than ``ep.id`` so a re-link
    to the episode the file already holds is allowed.

    Raises:
        EpisodeShowMismatchError: The episode belongs to another show.
        EpisodeAlreadyTrackedError: The episode is tracked by a different file.
    """
    if file.show_id is not None and ep.show_id != file.show_id:
        raise EpisodeShowMismatchError("Episode does not belong to the file's show")
    if ep.file_tracked and old_episode_id != new_episode_id:
        raise EpisodeAlreadyTrackedError("Episode is already tracked by another file")

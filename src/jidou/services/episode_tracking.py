"""Helpers for setting and clearing episode tracking state.

The four tracking fields (``file_tracked``, ``file_tracked_at``,
``tracked_filename``, ``tracked_source``) always move together.  These
helpers are the single source of truth so that adding a new field only
requires a change here.
"""

from datetime import UTC, datetime

from jidou.models.episode import Episode


def mark_episode_tracked(
    ep: Episode,
    filename: str | None,
    source: str | None,
    tracked_at: datetime | None = None,
) -> None:
    """Mark *ep* as tracked by a specific file.

    Args:
        ep: Episode ORM object to mutate in place.
        filename: Path or name of the file that tracks this episode.
            May be ``None`` when restoring from a snapshot that had no filename.
        source: Origin of the tracking event (``"match"``, ``"import"``, etc.).
            May be ``None`` when restoring an orphan record that had no source.
        tracked_at: Explicit timestamp to use instead of ``datetime.now(UTC)``.
            Pass the value preserved from a snapshot when restoring tracking
            state so the original timestamp is not overwritten.
    """
    ep.file_tracked = True
    ep.file_tracked_at = tracked_at if tracked_at is not None else datetime.now(UTC)
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

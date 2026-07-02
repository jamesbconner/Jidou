"""Helpers for setting and clearing episode tracking state.

The four tracking fields (``file_tracked``, ``file_tracked_at``,
``tracked_filename``, ``tracked_source``) always move together.  These
helpers are the single source of truth so that adding a new field only
requires a change here.
"""

from datetime import UTC, datetime

from jidou.models.episode import Episode

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

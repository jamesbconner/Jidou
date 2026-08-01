"""Helpers for setting and clearing episode watch state.

The two watch fields (``watched``, ``watched_at``) always move together.
These helpers are the single source of truth so that adding a new field
only requires a change here, mirroring the ``file_tracked``/
``file_tracked_at`` pair in :mod:`jidou.services.episode_tracking`.
"""

from datetime import UTC, datetime

from jidou.models.episode import Episode

# Sentinel distinguishing "caller passed None" from "caller omitted watched_at".
_UNSET: object = object()


def mark_episode_watched(
    ep: Episode,
    watched_at: datetime | None = _UNSET,  # type: ignore[assignment]
) -> None:
    """Mark *ep* as watched.

    Args:
        ep: Episode ORM object to mutate in place.
        watched_at: Explicit timestamp for ``watched_at``. Omit (or do not
            pass the keyword) to use ``datetime.now(UTC)``.
    """
    ep.watched = True
    ep.watched_at = datetime.now(UTC) if watched_at is _UNSET else watched_at


def clear_episode_watched(ep: Episode) -> None:
    """Clear watch state from *ep*.

    Args:
        ep: Episode ORM object to mutate in place.
    """
    ep.watched = False
    ep.watched_at = None

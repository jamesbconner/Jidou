"""Decides whether a show opted in to TMDB season 0 (Specials) metadata."""

from jidou.models.show import Show

SPECIALS_SEASON = 0


def wants_specials(show: Show) -> bool:
    """Return True when *show* should have its TMDB season 0 episodes synced.

    A show opts in with the ``sync_specials`` toggle, or by having any season
    alias that maps to season 0 (so a release named "<show> - Omake Shorts - 01"
    can resolve to an episode that actually exists).

    Args:
        show: The show to check.

    Returns:
        True when the toggle is on or a season alias points at season 0.

    Examples:
        >>> wants_specials(Show(title="Example Show", season_aliases={"omake shorts": 0}))
        True
    """
    if show.sync_specials:
        return True
    return SPECIALS_SEASON in (show.season_aliases or {}).values()

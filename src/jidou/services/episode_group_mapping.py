"""Build and query a season/cour-position -> real episode map from TMDB episode_groups.

TMDB's episode_groups let a show's episodes be organized differently than its
own season/episode structure -- e.g. a single-season, absolute-numbered show
(TMDB season 1, episodes 1-38) whose release group instead organizes files
into "Season 01"/"Season 02" folders that don't correspond to any real TMDB
season. Two TMDB group types are useful here:

- type 6 ("Production"): commonly used by TMDB editors to describe exactly
  this kind of cour-merged broadcast grouping -- its sub-group boundaries
  tend to match what a release group calls "Season N".
- type 2 ("Absolute"): TMDB's documented type for pure sequential episode
  numbering, used when no season grouping is declared in the filename/folder
  at all.

A show may have several episode_groups of the same type submitted by
different TMDB editors; only the first candidate of each type found in the
show's ``episode_groups`` summary is used. Per-show override of which group
to trust is not implemented -- see the tracking issue for that follow-up.
"""

import logging
from typing import Any, cast

from jidou.services.tmdb import TMDBService

logger = logging.getLogger(__name__)

# Preference order when a filename/folder declares a season number that
# doesn't match TMDB's own season structure.
_DECLARED_SEASON_GROUP_TYPES = (6, 2)

# Preference order when no season is declared at all (pure absolute numbering).
_ABSOLUTE_GROUP_TYPES = (2, 6)

_FETCHED_GROUP_TYPES = frozenset({6, 2})

# breakdowns: {group_type: {sub_group_order: [(season_number, episode_number), ...]}}
GroupBreakdowns = dict[int, dict[int, list[tuple[int, int]]]]

# The JSON-serializable shape stored on Show.episode_group_map:
# {"<group_type>": {"<sub_group_order>": {"<position>": [season_number, episode_number]}}}
StoredGroupMap = dict[str, dict[str, dict[str, list[int]]]]


def _extract_sub_groups(detail: dict[str, Any]) -> dict[int, list[tuple[int, int]]]:
    """Return ``{sub_group_order: [(season_number, episode_number), ...]}`` from a group detail.

    Specials (``season_number == 0``) are excluded. Episodes within each
    sub-group are sorted by their own ``order`` field rather than trusting
    response ordering.

    Args:
        detail: Raw response from :meth:`TMDBService.get_episode_group`.

    Returns:
        Mapping from sub-group order to its ordered (season, episode) pairs.
    """
    by_order: dict[int, list[tuple[int, int]]] = {}
    for sub_group in detail.get("groups", []):
        order = sub_group.get("order")
        if order is None:
            continue
        episodes = [
            ep for ep in sub_group.get("episodes", []) if (ep.get("season_number") or 0) > 0
        ]
        if not episodes:
            continue
        episodes.sort(key=lambda ep: ep.get("order", 0))
        pairs = [
            (ep["season_number"], ep["episode_number"])
            for ep in episodes
            if ep.get("season_number") is not None and ep.get("episode_number") is not None
        ]
        if pairs:
            by_order[order] = pairs
    return by_order


async def fetch_group_breakdowns(
    tmdb: TMDBService, episode_groups: list[dict[str, Any]] | None
) -> GroupBreakdowns:
    """Fetch and structure the type 6 and type 2 episode_groups breakdowns, if present.

    Best-effort: a fetch failure for one group type is logged and skipped
    rather than raised, so a TMDB hiccup never aborts the whole show sync.

    Args:
        tmdb: Configured TMDBService instance.
        episode_groups: The show's episode_groups summary list (from
            :meth:`TMDBService.get_episode_groups`).

    Returns:
        Breakdowns for whichever of type 6 / type 2 exist on the show and
        were fetched successfully. Empty if neither is present.
    """
    if not episode_groups:
        return {}

    result: GroupBreakdowns = {}
    for group_type in _FETCHED_GROUP_TYPES:
        candidate = next((g for g in episode_groups if g.get("type") == group_type), None)
        if candidate is None or not candidate.get("id"):
            continue
        try:
            detail = await tmdb.get_episode_group(candidate["id"])
        except Exception:
            logger.warning(
                "Failed to fetch episode_group id=%s type=%d",
                candidate.get("id"),
                group_type,
                exc_info=True,
            )
            continue
        sub_groups = _extract_sub_groups(detail)
        if sub_groups:
            result[group_type] = sub_groups
    return result


def to_storage_map(breakdowns: GroupBreakdowns) -> StoredGroupMap | None:
    """Convert fetched breakdowns into the JSON-serializable shape for ``Show.episode_group_map``.

    Args:
        breakdowns: Result of :func:`fetch_group_breakdowns`.

    Returns:
        The nested, string-keyed map ready to assign to
        ``Show.episode_group_map``, or None if *breakdowns* is empty.
    """
    if not breakdowns:
        return None
    return {
        str(group_type): {
            str(order): {
                str(position): [season_number, episode_number]
                for position, (season_number, episode_number) in enumerate(pairs, start=1)
            }
            for order, pairs in sub_groups.items()
        }
        for group_type, sub_groups in breakdowns.items()
    }


def flatten_for_absolute_numbering(breakdowns: GroupBreakdowns) -> dict[tuple[int, int], int]:
    """Build a ``{(season_number, episode_number): absolute_position}`` map for Episode rows.

    Uses whichever of type 2 ("Absolute") or type 6 ("Production") was
    fetched, preferring type 2 -- the documented TMDB type for pure
    sequential numbering -- and concatenates its sub-groups in ``order``
    sequence to derive each episode's 1-based absolute position.

    Args:
        breakdowns: Result of :func:`fetch_group_breakdowns`.

    Returns:
        Mapping from (season_number, episode_number) to its absolute
        position, or an empty dict if neither group type was fetched.
    """
    for group_type in _ABSOLUTE_GROUP_TYPES:
        sub_groups = breakdowns.get(group_type)
        if not sub_groups:
            continue
        result: dict[tuple[int, int], int] = {}
        position = 0
        for order in sorted(sub_groups):
            for season_number, episode_number in sub_groups[order]:
                position += 1
                result[(season_number, episode_number)] = position
        return result
    return {}


def resolve_declared_season(
    episode_group_map: dict[str, object] | None,
    declared_season: int,
    episode: int,
) -> tuple[int, int] | None:
    """Resolve a declared (season, episode) pair that doesn't exist in TMDB's real structure.

    Tries the type 6 ("Production") breakdown first, then type 2
    ("Absolute") -- fansub release groups' own "Season N" folder convention
    most often matches how TMDB editors group cours under type 6.

    Args:
        episode_group_map: The show's stored ``episode_group_map`` (from
            :func:`to_storage_map`), or None if never built.
        declared_season: The season number derived from the file's folder
            or filename, which failed a direct (season_number, episode_number)
            lookup.
        episode: The episode number within that declared season.

    Returns:
        The real ``(season_number, episode_number)`` this file actually
        corresponds to, or None if no group data resolves it.
    """
    if not episode_group_map:
        return None
    # episode_group_map is typed loosely (dict[str, object]) because that's
    # what the Show.episode_group_map JSONB column exposes; it's only ever
    # written by to_storage_map, so the nested shape is trusted here.
    stored = cast(StoredGroupMap, episode_group_map)
    for group_type in _DECLARED_SEASON_GROUP_TYPES:
        by_season = stored.get(str(group_type))
        if not by_season:
            continue
        positions = by_season.get(str(declared_season))
        if not positions:
            continue
        pair = positions.get(str(episode))
        if pair is not None:
            return pair[0], pair[1]
    return None

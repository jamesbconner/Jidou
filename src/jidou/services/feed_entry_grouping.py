"""Group feed entries by the show name parsed from their release titles."""

import re
from dataclasses import dataclass, field

from jidou.services.feed_fetch import FeedEntry
from jidou.services.filename_parser import parse_release_title

MAX_SAMPLE_TITLES = 3
_WHITESPACE = re.compile(r"\s+")


@dataclass
class FeedEntryGroup:
    """Entries of one feed that appear to belong to the same show.

    Attributes:
        parsed_name: Show name as parsed from the first entry's title (original
            casing), or None when no name could be parsed.
        entry_count: Number of entries in the group.
        season_min: Lowest season number seen, if any.
        season_max: Highest season number seen, if any.
        episode_min: Lowest episode number seen, if any.
        episode_max: Highest episode number seen, if any.
        sample_titles: Up to :data:`MAX_SAMPLE_TITLES` raw titles.
        titles: Every raw title in the group (used to feed the regex suggestor
            in a later step; not part of the list response).
    """

    parsed_name: str | None
    entry_count: int = 0
    season_min: int | None = None
    season_max: int | None = None
    episode_min: int | None = None
    episode_max: int | None = None
    sample_titles: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


def _min_opt(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else min(current, value)


def _max_opt(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else max(current, value)


def group_entries(entries: list[FeedEntry]) -> list[FeedEntryGroup]:
    """Group *entries* by case/whitespace-insensitive parsed show name.

    Uses the regex-only release-title parser (no LLM call per entry). Entries
    whose name cannot be parsed land in a single group with
    ``parsed_name=None`` so nothing is hidden from the user.

    Args:
        entries: Entries from :class:`FeedFetchService`.

    Returns:
        Groups ordered by entry count (descending), then name.
    """
    groups: dict[str, FeedEntryGroup] = {}
    for entry in entries:
        parsed = parse_release_title(entry.title)
        name = _WHITESPACE.sub(" ", parsed.show_name).strip() if parsed.show_name else None
        key = name.casefold() if name else ""
        group = groups.get(key)
        if group is None:
            group = groups[key] = FeedEntryGroup(parsed_name=name)
        group.entry_count += 1
        group.season_min = _min_opt(group.season_min, parsed.season)
        group.season_max = _max_opt(group.season_max, parsed.season)
        group.episode_min = _min_opt(group.episode_min, parsed.episode)
        group.episode_max = _max_opt(group.episode_max, parsed.episode)
        group.titles.append(entry.title)
        if len(group.sample_titles) < MAX_SAMPLE_TITLES:
            group.sample_titles.append(entry.title)

    return sorted(
        groups.values(),
        key=lambda g: (-g.entry_count, (g.parsed_name or "").casefold()),
    )

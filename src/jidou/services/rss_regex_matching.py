"""Evaluate include/exclude regex filters against release titles.

Used to show a user, before anything is saved, which of a feed's current
releases a filter would pick up. The semantics mirror YaRSS2's
``RSSFeedHandler.update_rssfeeds_dict_matching`` (``yarss2/rssfeed_handling.py``,
used by both its scheduler and its subscription dialog preview):

* a title is selected only if the include pattern ``re.search``-matches it, with
  a per-pattern ignore-case flag;
* a selected title is dropped if the exclude pattern also matches;
* an **empty or missing include pattern selects nothing** (YaRSS2 only marks an
  item as matching when an include pattern exists and matches); an empty
  exclude pattern excludes nothing.

Known differences from YaRSS2 (Python 2): it matches against UTF-8 *bytes*, so
quantifiers, ``.`` and case-folding can behave differently for non-ASCII
titles; and it additionally skips items older than the subscription's
``last_match`` timestamp, which this report does not model. The report answers
"which of these titles does the filter select", not "which would be downloaded
on the next run".

Patterns are user- or LLM-supplied and run server-side, and Python's ``re``
cannot be interrupted, so inputs are bounded: titles are truncated to
:data:`MAX_TITLE_LENGTH` characters and callers cap pattern length (see
``FeedRegexTestRequest``). That limits, but does not eliminate, pathological
backtracking; this is a single-tenant, authenticated endpoint.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

MAX_TITLE_LENGTH = 300


def compile_pattern(pattern: str | None, ignorecase: bool) -> re.Pattern[str] | None:
    """Compile one YaRSS2 include/exclude pattern.

    Args:
        pattern: Regex source. None or empty means "no pattern".
        ignorecase: Whether matching ignores case.

    Returns:
        The compiled pattern, or None when *pattern* is None or empty.

    Raises:
        re.error: If *pattern* is not a valid regular expression.
    """
    if not pattern:
        return None
    return re.compile(pattern, re.IGNORECASE if ignorecase else 0)


@dataclass(frozen=True)
class CompiledFilter:
    """A compiled include/exclude pair with YaRSS2 selection semantics.

    Attributes:
        include: Include pattern, or None. None selects nothing.
        exclude: Exclude pattern, or None for no exclusion.
    """

    include: re.Pattern[str] | None
    exclude: re.Pattern[str] | None

    def accepts(self, title: str) -> bool:
        """Return whether the filter selects *title*.

        Args:
            title: Release title, already truncated by the caller if needed.

        Returns:
            True when the include pattern matches and the exclude pattern, if
            any, does not. Without an include pattern nothing is selected.
        """
        if self.include is None or self.include.search(title) is None:
            return False
        return self.exclude is None or self.exclude.search(title) is None


@dataclass(frozen=True)
class RegexMatchReport:
    """Which titles a filter selects.

    Attributes:
        matched: Titles the filter would download, in input order.
        unmatched: Titles it would skip, in input order.
    """

    matched: list[str]
    unmatched: list[str]

    @property
    def total(self) -> int:
        """Number of titles evaluated."""
        return len(self.matched) + len(self.unmatched)


def evaluate_regex(
    titles: Sequence[str],
    *,
    include: str | None,
    exclude: str | None,
    include_ignorecase: bool = True,
    exclude_ignorecase: bool = True,
) -> RegexMatchReport:
    """Split *titles* into those the filter selects and those it skips.

    Args:
        titles: Release titles to evaluate.
        include: Include pattern. None or empty selects nothing, as in YaRSS2.
        exclude: Exclude pattern, or None/empty for no exclude filter.
        include_ignorecase: Case-insensitive include matching.
        exclude_ignorecase: Case-insensitive exclude matching.

    Returns:
        A :class:`RegexMatchReport`.

    Raises:
        re.error: If either pattern does not compile.
    """
    # Include compiles first so its error wins when both patterns are invalid.
    rule = CompiledFilter(
        include=compile_pattern(include, include_ignorecase),
        exclude=compile_pattern(exclude, exclude_ignorecase),
    )

    matched: list[str] = []
    unmatched: list[str] = []
    for title in titles:
        (matched if rule.accepts(title[:MAX_TITLE_LENGTH]) else unmatched).append(title)
    return RegexMatchReport(matched=matched, unmatched=unmatched)

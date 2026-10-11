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
    include_re = (
        re.compile(include, re.IGNORECASE if include_ignorecase else 0) if include else None
    )
    exclude_re = (
        re.compile(exclude, re.IGNORECASE if exclude_ignorecase else 0) if exclude else None
    )

    matched: list[str] = []
    unmatched: list[str] = []
    for title in titles:
        probe = title[:MAX_TITLE_LENGTH]
        selected = include_re is not None and include_re.search(probe) is not None
        if selected and exclude_re is not None and exclude_re.search(probe) is not None:
            selected = False
        (matched if selected else unmatched).append(title)
    return RegexMatchReport(matched=matched, unmatched=unmatched)

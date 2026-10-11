"""Decide whether a feed entry group is already covered by a subscription.

A subscription's include/exclude regexes are what YaRSS2 actually applies to
feed titles, so matching them against a group's titles answers "would this
show be downloaded?" without depending on how the show name was parsed.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscriptionRule:
    """The parts of an RSS subscription needed to match feed titles.

    Attributes:
        subscription_id: Database id of the subscription.
        show_id: Library show the subscription is linked to, if any.
        regex_include: Title must match this pattern (``re.search``).
        regex_exclude: Title must not match this pattern.
        include_ignorecase: Whether ``regex_include`` ignores case.
        exclude_ignorecase: Whether ``regex_exclude`` ignores case.
    """

    subscription_id: int
    show_id: int | None
    regex_include: str | None
    regex_exclude: str | None = None
    include_ignorecase: bool = True
    exclude_ignorecase: bool = True


@dataclass(frozen=True)
class _CompiledRule:
    subscription_id: int
    show_id: int | None
    include: re.Pattern[str] | None
    exclude: re.Pattern[str] | None

    def accepts(self, title: str) -> bool:
        if self.include is None or self.include.search(title) is None:
            return False
        return self.exclude is None or self.exclude.search(title) is None


def _compile(pattern: str | None, ignorecase: bool, subscription_id: int) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE if ignorecase else 0)
    except re.error as exc:
        logger.warning("Skipping invalid regex for subscription id=%d: %s", subscription_id, exc)
        return None


class SubscriptionMatcher:
    """Match groups of feed titles to subscriptions on that feed.

    Patterns are compiled once at construction. Rules are tried in
    subscription-id order so the result is deterministic.

    Args:
        rules: Active, published subscriptions of one feed.
    """

    def __init__(self, rules: list[SubscriptionRule]) -> None:
        ordered = sorted(rules, key=lambda r: r.subscription_id)
        self._compiled = [
            _CompiledRule(
                subscription_id=r.subscription_id,
                show_id=r.show_id,
                include=_compile(r.regex_include, r.include_ignorecase, r.subscription_id),
                # An invalid exclude must not silently turn into "no exclusion";
                # the include pattern is still what decides the match.
                exclude=_compile(r.regex_exclude, r.exclude_ignorecase, r.subscription_id),
            )
            for r in ordered
        ]

    def find(self, titles: list[str], show_id: int | None = None) -> int | None:
        """Return the id of the subscription covering *titles*, if any.

        A subscription whose regexes accept at least one title wins. Failing
        that, a subscription linked to *show_id* counts.

        Args:
            titles: Raw entry titles of one group.
            show_id: Library show the group resolved to, if any.

        Returns:
            Subscription id, or None when the group is not subscribed.
        """
        for rule in self._compiled:
            if any(rule.accepts(t) for t in titles):
                return rule.subscription_id
        if show_id is not None:
            for rule in self._compiled:
                if rule.show_id == show_id:
                    return rule.subscription_id
        return None

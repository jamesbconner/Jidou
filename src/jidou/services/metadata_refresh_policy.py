"""Pure policy for choosing which shows get their TMDB metadata refreshed.

No I/O lives here: callers load :class:`ShowRefreshFacts` (see
``metadata_refresh_candidates``), and this module decides which shows are due,
why, and in what order. Keeping the rules as small predicates makes each one
testable on its own and lets the SQL layer stay a dumb loader.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum

from jidou.config import settings

# TMDB statuses that mean "no more episodes expected" -- these are rechecked on
# the long interval. "Released" is the movie equivalent.
ENDED_STATUSES = frozenset({"Ended", "Cancelled", "Released"})


class RefreshReason(IntEnum):
    """Why a show is due. A lower value means a higher priority."""

    CONTRADICTORY = 0
    NEVER_REFRESHED = 1
    SEASON_FULLY_AIRED = 2
    ZERO_VOTES = 3
    AIRING_DUE = 4
    STALE = 5
    ENDED_RECHECK = 6


@dataclass(frozen=True, slots=True)
class ShowRefreshFacts:
    """The slice of a show the policy needs, loaded without full ORM rows.

    Attributes:
        show_id: Show primary key.
        title: Display title (for logging/results).
        media_type: ``"tv"`` or ``"movie"``.
        status: Stored TMDB status, if any.
        metadata_refreshed_at: Last refresh time, ``None`` if never.
        vote_count: Stored TMDB vote count.
        next_air_date: ``next_episode_to_air.air_date``, if any.
        last_air_date: Last air date (movies fall back to their release date).
        latest_season_fully_aired: Whether every episode of the highest
            non-special season has aired; ``None`` when there are no episodes.
        latest_season_last_air: Air date of the last episode of that season,
            taken from the episode rows (``None`` when there are none). Used
            instead of ``Show.last_air_date``, which only moves when a sync
            happens to run.
        has_rss_subscription: Whether any RSS subscription links to the show.
    """

    show_id: int
    title: str
    media_type: str
    status: str | None
    metadata_refreshed_at: datetime | None
    vote_count: int
    next_air_date: date | None
    last_air_date: date | None
    latest_season_fully_aired: bool | None
    latest_season_last_air: date | None
    has_rss_subscription: bool


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Thresholds and the clock for one refresh run.

    Attributes:
        now: Timezone-aware "current time"; its UTC date is "today".
        limit: Maximum shows to refresh this run.
        stale_days: Interval for shows with an unknown status and for
            zero-vote shows.
        airing_days: Interval for shows still expected to air.
        ended_days: Interval for ended/cancelled/released shows.
        lookback_years: Shows whose last air date is older are ignored.
        min_recheck: Minimum gap between refreshes of the same show (except
            never-refreshed ones), so permanently odd TMDB data can't crowd
            out every other show on every run.
    """

    now: datetime
    limit: int
    stale_days: int
    airing_days: int
    ended_days: int
    lookback_years: int
    min_recheck: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        """Reject naive datetimes, which would silently compare wrongly.

        Raises:
            ValueError: If ``now`` has no timezone.
        """
        if self.now.tzinfo is None:
            raise ValueError("RefreshPolicy.now must be timezone-aware")

    @property
    def today(self) -> date:
        """Today's date in UTC."""
        return self.now.astimezone(UTC).date()

    @classmethod
    def from_settings(cls, now: datetime) -> "RefreshPolicy":
        """Build a policy from application settings.

        Args:
            now: Timezone-aware current time.

        Returns:
            A policy using the ``show_metadata_refresh_*`` settings.
        """
        return cls(
            now=now,
            limit=settings.show_metadata_refresh_limit_per_run,
            stale_days=settings.show_metadata_refresh_stale_days,
            airing_days=settings.show_metadata_refresh_airing_days,
            ended_days=settings.show_metadata_refresh_ended_days,
            lookback_years=settings.show_metadata_refresh_lookback_years,
        )

    def lookback_cutoff(self) -> date:
        """Return the oldest last-air date still inside the lookback window."""
        today = self.today
        try:
            return today.replace(year=today.year - self.lookback_years)
        except ValueError:  # Feb 29 in a non-leap target year
            return today.replace(year=today.year - self.lookback_years, day=28)


Rule = Callable[[ShowRefreshFacts, RefreshPolicy], bool]


def is_in_lookback(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    """Whether the show aired recently enough to be worth refreshing.

    A show with no known last air date stays eligible: unknown is exactly the
    sort of stale record this job exists to fix.

    Args:
        facts: Loaded show facts.
        policy: Active policy.

    Returns:
        ``True`` if ``last_air_date`` is unknown or inside the window.
    """
    return facts.last_air_date is None or facts.last_air_date >= policy.lookback_cutoff()


def _age_exceeds(facts: ShowRefreshFacts, policy: RefreshPolicy, days: int) -> bool:
    refreshed = facts.metadata_refreshed_at
    return refreshed is not None and refreshed <= policy.now - timedelta(days=days)


def _past_min_recheck(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    refreshed = facts.metadata_refreshed_at
    return refreshed is not None and refreshed <= policy.now - policy.min_recheck


def _never_refreshed(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    return facts.metadata_refreshed_at is None


def _contradictory(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    """Stored 'next episode' is already in the past, so the record is provably stale."""
    return (
        _past_min_recheck(facts, policy)
        and facts.next_air_date is not None
        and facts.next_air_date < policy.today
    )


def _season_fully_aired(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    """The latest season finished after the last refresh, so status may have changed."""
    refreshed = facts.metadata_refreshed_at
    return (
        _past_min_recheck(facts, policy)
        and refreshed is not None
        and bool(facts.latest_season_fully_aired)
        and facts.latest_season_last_air is not None
        and facts.latest_season_last_air >= refreshed.astimezone(UTC).date()
    )


def _zero_votes(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    return facts.vote_count == 0 and _age_exceeds(facts, policy, policy.stale_days)


def _airing_due(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    return (
        facts.status is not None
        and facts.status not in ENDED_STATUSES
        and _age_exceeds(facts, policy, policy.airing_days)
    )


def _stale(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    return facts.status is None and _age_exceeds(facts, policy, policy.stale_days)


def _ended_recheck(facts: ShowRefreshFacts, policy: RefreshPolicy) -> bool:
    return facts.status in ENDED_STATUSES and _age_exceeds(facts, policy, policy.ended_days)


# Ordered by priority; classify() returns the first match.
RULES: tuple[tuple[RefreshReason, Rule], ...] = (
    (RefreshReason.CONTRADICTORY, _contradictory),
    (RefreshReason.NEVER_REFRESHED, _never_refreshed),
    (RefreshReason.SEASON_FULLY_AIRED, _season_fully_aired),
    (RefreshReason.ZERO_VOTES, _zero_votes),
    (RefreshReason.AIRING_DUE, _airing_due),
    (RefreshReason.STALE, _stale),
    (RefreshReason.ENDED_RECHECK, _ended_recheck),
)


def classify(facts: ShowRefreshFacts, policy: RefreshPolicy) -> RefreshReason | None:
    """Return the highest-priority reason this show is due, or ``None``.

    Args:
        facts: Loaded show facts.
        policy: Active policy.

    Returns:
        The first matching :class:`RefreshReason`, else ``None``.
    """
    for reason, rule in RULES:
        if rule(facts, policy):
            return reason
    return None


def select_candidates(
    facts: list[ShowRefreshFacts], policy: RefreshPolicy
) -> list[tuple[ShowRefreshFacts, RefreshReason]]:
    """Pick the shows to refresh this run, highest priority first.

    Shows outside the lookback window or matching no rule are dropped. The
    rest sort by reason, then RSS-subscribed shows first (they drive the
    subscription recommendations), then never-refreshed/oldest refresh first,
    then id for determinism. The per-run cap is applied last.

    Args:
        facts: Loaded show facts.
        policy: Active policy.

    Returns:
        At most ``policy.limit`` ``(facts, reason)`` pairs.
    """
    due: list[tuple[ShowRefreshFacts, RefreshReason]] = []
    for f in facts:
        if not is_in_lookback(f, policy):
            continue
        reason = classify(f, policy)
        if reason is not None:
            due.append((f, reason))

    epoch = datetime.min.replace(tzinfo=UTC)
    due.sort(
        key=lambda pair: (
            pair[1],
            not pair[0].has_rss_subscription,
            pair[0].metadata_refreshed_at or epoch,
            pair[0].show_id,
        )
    )
    return due[: policy.limit]

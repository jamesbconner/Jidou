"""Pydantic schemas for RSS feed and subscription API endpoints."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jidou.schemas.show_schema import ShowCreate


def _validate_regex(v: str | None) -> str | None:
    """Compile *v* as a Python regex, raising ValueError if invalid."""
    if v is not None:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
    return v


MAX_REGEX_SAMPLES = 3
MAX_PREVIOUS_SUGGESTIONS = 5


class RegexHintSample(BaseModel):
    """A real release title from a feed plus the regex_include that matches it.

    Attributes:
        sample_name: Example release title. May be empty (migrated legacy hints).
        hint: Python regex that correctly matches ``sample_name``.
    """

    sample_name: str = ""
    hint: str = Field(min_length=1)

    @field_validator("hint")
    @classmethod
    def validate_hint(cls, v: str) -> str:
        """Reject hints that fail to compile as Python regexes."""
        _validate_regex(v)
        return v


class RssShowBrief(BaseModel):
    """Minimal show info embedded in subscription responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str | None
    poster_path: str | None


class RssFeedCreate(BaseModel):
    """Request body for creating an RSS feed."""

    remote_key: str | None = None
    name: str
    url: str
    default_download_location: str | None = None
    default_move_completed: str | None = None
    active: bool = True
    regex_include_samples: list[RegexHintSample] | None = Field(
        default=None, max_length=MAX_REGEX_SAMPLES
    )
    regex_exclude_hint: str | None = None
    extra_config: dict[str, object] | None = None

    @field_validator("regex_exclude_hint")
    @classmethod
    def validate_regex_hint(cls, v: str | None) -> str | None:
        """Reject hints that fail to compile as Python regexes."""
        return _validate_regex(v)


class RssFeedUpdate(BaseModel):
    """Request body for updating an RSS feed — all fields optional."""

    remote_key: str | None = None
    name: str | None = None
    url: str | None = None
    default_download_location: str | None = None
    default_move_completed: str | None = None
    active: bool | None = None
    regex_include_samples: list[RegexHintSample] | None = Field(
        default=None, max_length=MAX_REGEX_SAMPLES
    )
    regex_exclude_hint: str | None = None
    extra_config: dict[str, object] | None = None

    @field_validator("regex_exclude_hint")
    @classmethod
    def validate_regex_hint(cls, v: str | None) -> str | None:
        """Reject hints that fail to compile as Python regexes."""
        return _validate_regex(v)


class RssFeedRead(BaseModel):
    """Full RSS feed record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    remote_key: str | None
    name: str
    url: str
    default_download_location: str | None
    default_move_completed: str | None
    active: bool
    regex_include_samples: list[RegexHintSample] | None
    regex_exclude_hint: str | None
    extra_config: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


class RssSubscriptionCreate(BaseModel):
    """Request body for creating an RSS subscription."""

    feed_id: int | None = None
    show_id: int | None = None
    name: str
    regex_include: str | None = None
    regex_exclude: str | None = None
    regex_include_ignorecase: bool = True
    regex_exclude_ignorecase: bool = True
    download_location: str | None = None
    move_completed: str | None = None
    active: bool = False
    enabled_in_config: bool = False
    label: str | None = None
    extra_config: dict[str, object] | None = None

    @field_validator("regex_include", "regex_exclude")
    @classmethod
    def validate_regex(cls, v: str | None) -> str | None:
        """Reject patterns that fail to compile as Python regexes."""
        return _validate_regex(v)


class RssSubscriptionUpdate(BaseModel):
    """Request body for updating an RSS subscription — all fields optional."""

    feed_id: int | None = None
    show_id: int | None = None
    name: str | None = None
    regex_include: str | None = None
    regex_exclude: str | None = None
    regex_include_ignorecase: bool | None = None
    regex_exclude_ignorecase: bool | None = None
    download_location: str | None = None
    move_completed: str | None = None
    active: bool | None = None
    enabled_in_config: bool | None = None
    label: str | None = None
    extra_config: dict[str, object] | None = None

    @field_validator("regex_include", "regex_exclude")
    @classmethod
    def validate_regex(cls, v: str | None) -> str | None:
        """Reject patterns that fail to compile as Python regexes."""
        return _validate_regex(v)


class RssSubscriptionRead(BaseModel):
    """Full RSS subscription record with embedded feed and show."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    remote_key: str | None
    feed_id: int | None
    show_id: int | None
    name: str
    regex_include: str | None
    regex_exclude: str | None
    regex_include_ignorecase: bool
    regex_exclude_ignorecase: bool
    download_location: str | None
    move_completed: str | None
    active: bool
    enabled_in_config: bool
    label: str | None
    last_match: str | None
    extra_config: dict[str, object] | None
    feed: RssFeedRead | None
    show: RssShowBrief | None
    created_at: datetime
    updated_at: datetime


class RssSubscriptionRecommendation(RssSubscriptionRead):
    """RSS subscription with a computed health-check recommendation."""

    recommendation: Literal["activate", "deactivate"]


class RssSubscriptionBulkPatchItem(BaseModel):
    """Single item in a bulk-patch request."""

    id: int
    active: bool


class RssConfigDiff(BaseModel):
    """Unified diff between the current DB-composed config and the last snapshot.

    Attributes:
        snapshot_id: Primary key of the snapshot the diff was taken against.
        snapshot_type: ``"import"`` or ``"pre_publish"``.
        snapshot_created_at: When that snapshot was captured.
        has_changes: Whether the diff is non-empty.
        diff: Unified diff lines; empty if the composed config is identical
            to the snapshot.
    """

    snapshot_id: int
    snapshot_type: str
    snapshot_created_at: datetime
    has_changes: bool
    diff: list[str]


class RssRegexSuggestRequest(BaseModel):
    """Optional unsaved context for an LLM regex suggestion.

    Attributes:
        feed_id: Feed currently selected in the edit form. When the field is
            present it overrides the subscription's persisted feed for hint
            lookup (``None`` means "no feed"); when omitted the persisted feed
            is used.
        previous: Earlier ``regex_include`` suggestions from this session. When
            non-empty the request is a re-suggest: the LLM cache is bypassed and
            the model is told not to repeat these.
    """

    feed_id: int | None = None
    previous: list[str] = Field(default_factory=list, max_length=MAX_PREVIOUS_SUGGESTIONS)


class RssRegexSuggestion(BaseModel):
    """LLM-generated regex suggestion for an RSS subscription filter.

    Attributes:
        regex_include: Suggested include regex (match wanted torrents).
        regex_exclude: Suggested exclude regex (filter out unwanted releases).
        model: LLM model identifier that produced the suggestion.
        cached: Whether the response came from the LLM cache.
    """

    regex_include: str
    regex_exclude: str
    model: str
    cached: bool


class FeedEntryGroupRead(BaseModel):
    """Feed entries grouped by the show name parsed from their titles.

    Attributes:
        parsed_name: Parsed show name, or None for entries that could not be
            parsed.
        entry_count: Number of entries in the group.
        season_min: Lowest season seen, if any.
        season_max: Highest season seen, if any.
        episode_min: Lowest episode seen, if any.
        episode_max: Highest episode seen, if any.
        sample_titles: Up to three raw entry titles.
        library_show: Library show whose alias/title exactly matches the parsed
            name, if any.
        existing_subscription_id: An active subscription on this feed that
            already covers the group (its regexes match the group's titles, or
            it is linked to ``library_show``), if any.
    """

    parsed_name: str | None
    entry_count: int
    season_min: int | None
    season_max: int | None
    episode_min: int | None
    episode_max: int | None
    sample_titles: list[str]
    library_show: RssShowBrief | None
    existing_subscription_id: int | None


class FeedEntriesRead(BaseModel):
    """Response for browsing a feed's entries.

    Attributes:
        feed_id: Feed the entries were fetched from.
        total_entries: Entries returned (after the server-side cap).
        truncated: The feed had more entries than the cap.
        malformed: The feed XML was not well-formed; entries may be incomplete.
        cached: Served from the short-lived entry cache.
        groups: Entries grouped by parsed show name.
    """

    feed_id: int
    total_entries: int
    truncated: bool
    malformed: bool
    cached: bool
    groups: list[FeedEntryGroupRead]


MAX_REGEX_PATTERN_LENGTH = 512


class RegexMatchReportRead(BaseModel):
    """Which of a feed group's current titles a regex filter selects.

    Attributes:
        matched_titles: Titles the filter would download.
        unmatched_titles: Titles the filter would skip.
        total: Number of titles evaluated.
    """

    matched_titles: list[str]
    unmatched_titles: list[str]
    total: int


class FeedRegexSuggestRequest(BaseModel):
    """Request a regex suggestion for a group of a feed's entries.

    Attributes:
        parsed_name: The group's ``parsed_name`` from the feed entries response.
            The group's real release titles are re-read server-side (from the
            short-lived feed cache), never trusted from the client.
        show_title: Title of the show the user picked (library or TMDB). Used as
            the prompt's show label; ``parsed_name`` is used when omitted.
        previous: Earlier ``regex_include`` suggestions this session. When
            non-empty the LLM cache is bypassed and the model must differ.
    """

    parsed_name: str = Field(min_length=1, max_length=300)
    show_title: str | None = Field(default=None, max_length=300)
    previous: list[str] = Field(default_factory=list, max_length=MAX_PREVIOUS_SUGGESTIONS)


class FeedRegexSuggestion(RssRegexSuggestion):
    """A regex suggestion plus how it fares against the group's real titles.

    Attributes:
        match: Titles the suggested filter would and would not select.
    """

    match: RegexMatchReportRead


class FeedRegexTestRequest(BaseModel):
    """Preview a hand-edited filter against a feed group's current titles.

    Attributes:
        parsed_name: The group's ``parsed_name`` from the feed entries response.
        regex_include: Include pattern. Empty/None selects nothing, matching
            YaRSS2 (a subscription without an include pattern never matches).
        regex_exclude: Exclude pattern; empty/None means no exclude filter.
        regex_include_ignorecase: Case-insensitive include matching.
        regex_exclude_ignorecase: Case-insensitive exclude matching.
    """

    parsed_name: str = Field(min_length=1, max_length=300)
    regex_include: str | None = Field(default=None, max_length=MAX_REGEX_PATTERN_LENGTH)
    regex_exclude: str | None = Field(default=None, max_length=MAX_REGEX_PATTERN_LENGTH)
    regex_include_ignorecase: bool = True
    regex_exclude_ignorecase: bool = True

    @field_validator("regex_include", "regex_exclude")
    @classmethod
    def validate_regex(cls, v: str | None) -> str | None:
        """Reject patterns that fail to compile as Python regexes."""
        return _validate_regex(v)


class FeedAddShowRequest(BaseModel):
    """Create (or reuse) a show and its subscription from one feed group.

    Exactly one of ``show_id`` (a show already in the library) or ``show`` (a
    TMDB result to add) must be given.

    Attributes:
        parsed_name: The group's ``parsed_name`` from the entries response.
            Taught as an alias of the chosen show so later files and entries
            named that way match it directly.
        show_id: Existing library show to subscribe.
        show: TMDB result to add to the library first.
        name: Subscription name; defaults to the show title.
        regex_include: Include pattern (empty/None selects nothing in YaRSS2).
        regex_exclude: Exclude pattern.
        regex_include_ignorecase: Case-insensitive include matching.
        regex_exclude_ignorecase: Case-insensitive exclude matching.
        enabled: When true the subscription is active and included in the next
            publish; when false it is saved in Jidou only.
        dry_run: Validate and report what would happen without writing.
    """

    parsed_name: str = Field(min_length=1, max_length=300)
    show_id: int | None = None
    show: ShowCreate | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    regex_include: str | None = Field(default=None, max_length=MAX_REGEX_PATTERN_LENGTH)
    regex_exclude: str | None = Field(default=None, max_length=MAX_REGEX_PATTERN_LENGTH)
    regex_include_ignorecase: bool = True
    regex_exclude_ignorecase: bool = True
    enabled: bool = False
    dry_run: bool = False

    @field_validator("regex_include", "regex_exclude")
    @classmethod
    def validate_regex(cls, v: str | None) -> str | None:
        """Reject patterns that fail to compile as Python regexes."""
        return _validate_regex(v)

    @model_validator(mode="after")
    def exactly_one_show_source(self) -> "FeedAddShowRequest":
        """Require exactly one of ``show_id`` and ``show``."""
        if (self.show_id is None) == (self.show is None):
            raise ValueError("Provide exactly one of show_id or show")
        return self


class FeedAddShowResult(BaseModel):
    """What an add-show-from-feed call did (or, for a dry run, would do).

    Attributes:
        show: The show; None when a dry run would create it.
        show_created: The show was (or would be) newly added to the library.
        subscription: The subscription; None when a dry run would create it.
        subscription_created: A new subscription was (or would be) created.
        adopted_stub: An unlinked subscription from an import was linked to the
            feed instead of creating a duplicate.
        alias_added: The parsed name was (or would be) added as a show alias.
        dry_run: Nothing was written.
    """

    show: RssShowBrief | None
    show_created: bool
    subscription: "RssSubscriptionRead | None"
    subscription_created: bool
    adopted_stub: bool
    alias_added: bool
    dry_run: bool

"""Pydantic schemas for RSS feed and subscription API endpoints."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

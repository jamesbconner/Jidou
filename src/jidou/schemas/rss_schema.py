"""Pydantic schemas for RSS feed and subscription API endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RssShowBrief(BaseModel):
    """Minimal show info embedded in subscription responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class RssFeedCreate(BaseModel):
    """Request body for creating an RSS feed."""

    remote_key: str | None = None
    name: str
    url: str
    default_download_location: str | None = None
    default_move_completed: str | None = None
    extra_config: dict[str, object] | None = None


class RssFeedUpdate(BaseModel):
    """Request body for updating an RSS feed — all fields optional."""

    remote_key: str | None = None
    name: str | None = None
    url: str | None = None
    default_download_location: str | None = None
    default_move_completed: str | None = None
    extra_config: dict[str, object] | None = None


class RssFeedRead(BaseModel):
    """Full RSS feed record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    remote_key: str | None
    name: str
    url: str
    default_download_location: str | None
    default_move_completed: str | None
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
    active: bool = True
    enabled_in_config: bool = False
    label: str | None = None
    extra_config: dict[str, object] | None = None


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

"""Pydantic schemas for the airing calendar API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from jidou.models.show import ContentType


class CalendarEpisode(BaseModel):
    """One episode airing within a requested calendar date range.

    Composes fields from both ``Episode`` and its parent ``Show`` so the
    frontend can render a calendar cell without a second round-trip per show.
    """

    episode_id: int
    show_id: int
    show_title: str
    poster_path: str | None
    season_number: int
    episode_number: int
    name: str
    air_date: date
    status: Literal["tracked", "missing", "upcoming"]
    # Mirrors Show.track_missing_episodes -- False means the user opted this
    # show out of missing-episode tracking (e.g. it deliberately has no RSS
    # feed), so the frontend shouldn't count a "missing" episode here toward
    # anything actionable.
    track_missing_episodes: bool
    content_type: ContentType | None = None
    genres: list[dict[str, object]] | None = Field(
        default=None,
        description='TMDB genre objects: [{"id": 16, "name": "Animation"}]',
    )


class CalendarSyncResult(BaseModel):
    """Result of re-syncing TMDB metadata for shows with a "missing" episode in a calendar range."""

    shows_synced: int
    shows_failed: int
    episodes_upserted: int

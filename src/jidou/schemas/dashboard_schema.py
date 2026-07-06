"""Pydantic schemas for the dashboard recently-added carousels API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class RecentShowItem(BaseModel):
    """A show card for the dashboard's "Recently Added Shows" carousel."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    media_type: str
    content_type: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    overview: str | None = None
    tagline: str | None = None
    vote_average: float | None = None
    genres: list[dict[str, object]] | None = None
    release_date: str | None = None
    status: str | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    runtime: int | None = None
    created_at: datetime
    adult: bool | None = None


class DashboardShowSummary(BaseModel):
    """The subset of a show's fields shown alongside an episode card."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content_type: str | None = None
    media_type: str
    poster_path: str | None = None
    vote_average: float | None = None
    genres: list[dict[str, object]] | None = None
    adult: bool | None = None


class RecentEpisodeItem(BaseModel):
    """An episode card for the dashboard's "Recently Added Episodes" carousel."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    season_number: int
    episode_number: int
    name: str
    overview: str | None = None
    air_date: date | None = None
    file_tracked_at: datetime | None = None
    still_path: str | None = None
    runtime: int | None = None
    show: DashboardShowSummary

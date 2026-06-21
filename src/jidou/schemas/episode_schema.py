"""Pydantic schemas for Episode API responses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EpisodeRead(BaseModel):
    """Full episode record returned by detail endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    tmdb_id: int
    season_number: int
    episode_number: int
    name: str
    overview: str | None = None
    air_date: date | None = None
    runtime: int | None = None
    absolute_episode_number: int | None = None
    episode_type: str | None = None
    still_path: str | None = None
    file_tracked: bool
    created_at: datetime
    updated_at: datetime


class EpisodeList(BaseModel):
    """Slim episode record returned by list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    season_number: int
    episode_number: int
    name: str
    air_date: date | None = None
    episode_type: str | None = None
    absolute_episode_number: int | None = None
    file_tracked: bool

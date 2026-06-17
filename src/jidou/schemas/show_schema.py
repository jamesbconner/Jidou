"""Pydantic schemas for Show API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShowCreate(BaseModel):
    """Payload for adding a show to the database.

    All fields mirror the TMDB search/trending response so the frontend can
    pass a result card directly to ``POST /shows`` without an extra round-trip.
    """

    tmdb_id: int
    title: str
    media_type: str = Field(default="tv", pattern="^(tv|movie)$")
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int = 0
    release_date: str | None = None
    original_language: str | None = None


class ShowPaths(BaseModel):
    """Payload for linking a show to SFTP / local filesystem paths."""

    remote_path: str | None = None
    local_path: str | None = None


class ShowRead(BaseModel):
    """Full show record returned by ``GET /shows/{id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    media_type: str
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int
    release_date: str | None = None
    original_language: str | None = None
    cached: bool
    remote_path: str | None = None
    local_path: str | None = None
    created_at: datetime
    updated_at: datetime


class ShowList(BaseModel):
    """Slim show record returned by ``GET /shows``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    media_type: str
    poster_path: str | None = None
    vote_average: float | None = None
    release_date: str | None = None
    remote_path: str | None = None
    local_path: str | None = None
    created_at: datetime

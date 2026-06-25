"""Pydantic schemas for WatchlistEntry API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShowBrief(BaseModel):
    """Minimal show info embedded in watchlist responses."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    tmdb_id: int
    poster_path: str | None = None


class WatchlistCreate(BaseModel):
    """Request body for adding a show to the watchlist."""

    show_id: int
    status: str = Field(
        default="planned",
        pattern="^(planned|watching|completed|on_hold|dropped)$",
    )
    notes: str | None = None
    position: int = 0


class WatchlistUpdate(BaseModel):
    """Request body for updating a watchlist entry — all fields optional."""

    status: str | None = Field(
        default=None,
        pattern="^(planned|watching|completed|on_hold|dropped)$",
    )
    notes: str | None = None
    position: int | None = None


class WatchlistRead(BaseModel):
    """Full watchlist entry record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    show: ShowBrief
    status: str
    notes: str | None = None
    position: int
    created_at: datetime
    updated_at: datetime


class WatchlistList(BaseModel):
    """Slim watchlist entry for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    show: ShowBrief
    status: str
    position: int
    created_at: datetime

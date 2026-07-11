"""Pydantic schemas for WatchlistEntry API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from jidou.models.watchlist import WatchlistStatus


class ShowBrief(BaseModel):
    """Minimal show info embedded in watchlist responses."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    tmdb_id: int
    poster_path: str | None = None


class WatchlistCreate(BaseModel):
    """Request body for adding a show to the watchlist."""

    show_id: int
    status: WatchlistStatus = WatchlistStatus.PLANNED
    notes: str | None = None
    position: int = 0


class WatchlistUpdate(BaseModel):
    """Request body for updating a watchlist entry — all fields optional."""

    status: WatchlistStatus | None = None
    notes: str | None = None
    position: int | None = None


class WatchlistPositionItem(BaseModel):
    """Position update for a single entry in a bulk reorder request."""

    id: int
    position: int


class WatchlistRead(BaseModel):
    """Full watchlist entry record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    show: ShowBrief
    status: WatchlistStatus
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
    status: WatchlistStatus
    position: int
    created_at: datetime

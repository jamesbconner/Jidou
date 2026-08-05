"""Pydantic schemas for WatchlistEntry API request/response validation."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from jidou.models.watchlist import WatchlistStatus


class ShowBrief(BaseModel):
    """Minimal show info embedded in watchlist responses."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    tmdb_id: int
    poster_path: str | None = None
    backdrop_path: str | None = None


class EpisodeBrief(BaseModel):
    """Minimal episode info for the watchlist's "next up" indicator.

    ``air_date`` is included deliberately unfiltered — the lowest unwatched
    episode may not have aired yet, and showing the date lets the user judge
    that for themselves rather than having it silently filtered out.
    """

    model_config = ConfigDict(from_attributes=True)

    season_number: int
    episode_number: int
    name: str
    air_date: date | None = None
    file_tracked: bool


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
    next_up: EpisodeBrief | None = None


class WatchlistList(BaseModel):
    """Slim watchlist entry for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    show_id: int
    show: ShowBrief
    status: WatchlistStatus
    position: int
    created_at: datetime

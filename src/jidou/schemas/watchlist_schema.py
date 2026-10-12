"""Pydantic schemas for WatchlistEntry API request/response validation."""

from datetime import date, datetime

from pydantic import BaseModel

from jidou.models.watchlist import WatchlistStatus
from jidou.schemas._base import ORMModel


class WatchlistShowBrief(ORMModel):
    """Minimal show info embedded in watchlist responses."""

    title: str
    tmdb_id: int
    poster_path: str | None = None
    backdrop_path: str | None = None


class WatchlistNextUpEpisode(ORMModel):
    """Minimal episode info for the watchlist's "next up" indicator.

    ``air_date`` is included deliberately unfiltered — the lowest unwatched
    episode may not have aired yet, and showing the date lets the user judge
    that for themselves rather than having it silently filtered out.
    """

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


class WatchlistRead(ORMModel):
    """Full watchlist entry record."""

    id: int
    show_id: int
    show: WatchlistShowBrief
    status: WatchlistStatus
    notes: str | None = None
    position: int
    created_at: datetime
    updated_at: datetime
    next_up: WatchlistNextUpEpisode | None = None

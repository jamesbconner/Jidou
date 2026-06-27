"""Pydantic schemas for orphaned tracking record API requests and responses."""

from datetime import datetime

from pydantic import BaseModel


class OrphanRead(BaseModel):
    """Orphaned tracking record returned by ``GET /orphans``."""

    id: int
    show_id: int
    show_title: str
    tracked_filename: str | None
    tracked_source: str
    old_season_number: int
    old_episode_number: int
    downloaded_file_id: int | None
    created_at: datetime


class OrphanResolveRequest(BaseModel):
    """Payload for resolving an orphaned tracking record."""

    episode_id: int

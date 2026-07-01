"""Pydantic schemas for admin API request/response validation."""

from pydantic import BaseModel


class StatsResponse(BaseModel):
    """Response model for ``GET /api/admin/stats``.

    All counts default to zero so the dashboard renders safely even when
    the database is empty or a query returns ``None``.
    """

    shows: int = 0
    episodes_tracked: int = 0
    episodes_total: int = 0
    files_needs_attention: int = 0
    files_added_1d: int = 0
    files_added_7d: int = 0
    files_added_30d: int = 0
    watchlist: int = 0
    background_tasks: int = 0
    dq_total: int = 0
    dq_no_path: int = 0
    dq_no_content_type: int = 0
    dq_no_episodes: int = 0
    dq_orphan: int = 0

"""Pydantic schemas for the airing calendar API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


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

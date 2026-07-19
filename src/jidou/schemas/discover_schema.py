"""Response schema for the show discovery feed."""

from pydantic import BaseModel, Field


class DiscoverResult(BaseModel):
    """A single TMDB item surfaced on the Discover page.

    Field names mirror TMDB's own raw response shape (``id``/``name``/
    ``title``/etc.) rather than Jidou's internal Show model, so the frontend
    can feed this directly into the existing TMDB-result-based add-to-library
    flow without a translation layer.
    """

    id: int
    media_type: str
    name: str | None = None
    title: str | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    release_date: str | None = None
    first_air_date: str | None = None
    original_language: str | None = None
    genre_ids: list[int] | None = None
    origin_country: list[str] | None = None
    adult: bool | None = None
    # Titles of the user's watchlist shows this was recommended because of.
    # Empty for items included only to fill out the feed from trending.
    seeded_from: list[str] = Field(default_factory=list)

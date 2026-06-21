"""Show model for movies and TV series metadata."""

from enum import StrEnum

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class ContentType(StrEnum):
    """User-assigned routing category for a show."""

    ANIME = "anime"
    TV = "tv"
    MOVIE = "movie"


class Show(TimestampMixin, Base):
    """Represents a movie or TV series discovered via TMDB."""

    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(20))  # "tv" or "movie" — from TMDB
    poster_path: Mapped[str | None] = mapped_column(String(500))
    backdrop_path: Mapped[str | None] = mapped_column(String(500))
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int] = mapped_column(default=0)
    release_date: Mapped[str | None] = mapped_column(String(20))
    original_language: Mapped[str | None] = mapped_column(String(10))
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    # User-assigned routing category (anime/tv/movie); None until explicitly set
    content_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Windows-safe sanitized title for local directory names
    sys_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Alternative names used to match parsed filenames; stored as a JSON array
    aliases: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # TMDB genres array: [{"id": 16, "name": "Animation"}, ...]
    genres: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    # ISO 3166-1 origin country codes: ["JP", "US", ...]
    origin_country: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # TMDB show status: "Returning Series", "Ended", "Cancelled", "Released", etc.
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # TV only: whether the show is currently in production
    in_production: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # TV only: total number of seasons
    number_of_seasons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # TV only: total number of episodes across all seasons
    number_of_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # TV only: broadcast networks / streaming services [{"id": 49, "name": "HBO", ...}]
    networks: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    # TV only: "Scripted", "Miniseries", "Documentary", "Reality", etc.
    show_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Episode runtime in minutes (TV: first value of episode_run_time; movie: runtime)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Short promotional tagline
    tagline: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Local filesystem path to this show's root directory
    local_path: Mapped[str | None] = mapped_column(String(1000))

    def __repr__(self) -> str:
        """Return a concise representation of the Show."""
        return f"<Show(tmdb_id={self.tmdb_id}, title={self.title!r})>"

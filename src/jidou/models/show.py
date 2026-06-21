"""Show model for movies and TV series metadata."""

from enum import StrEnum

from sqlalchemy import Boolean, Float, String, Text
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
    # Local filesystem path to this show's root directory
    local_path: Mapped[str | None] = mapped_column(String(1000))

    def __repr__(self) -> str:
        """Return a concise representation of the Show."""
        return f"<Show(tmdb_id={self.tmdb_id}, title={self.title!r})>"

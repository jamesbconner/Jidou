"""Show model for movies and TV series metadata."""

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class Show(TimestampMixin, Base):
    """Represents a movie or TV series discovered via TMDB."""

    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(20))  # "tv" or "movie"
    poster_path: Mapped[str | None] = mapped_column(String(500))
    backdrop_path: Mapped[str | None] = mapped_column(String(500))
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int] = mapped_column(default=0)
    release_date: Mapped[str | None] = mapped_column(String(20))
    original_language: Mapped[str | None] = mapped_column(String(10))
    cached: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        """Return a concise representation of the Show."""
        return f"<Show(tmdb_id={self.tmdb_id}, title={self.title!r})>"

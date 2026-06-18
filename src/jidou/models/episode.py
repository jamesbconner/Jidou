"""Episode model for TV show episodes."""

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class Episode(TimestampMixin, Base):
    """An individual TV show episode with TMDB metadata.

    Episodes are populated by the sync worker when it fetches season details
    from TMDB.  The ``file_tracked`` flag is set to ``True`` once a matching
    :class:`DownloadedFile` has been linked to this episode.
    """

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), index=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    season_number: Mapped[int] = mapped_column(Integer)
    episode_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    air_date: Mapped[date | None] = mapped_column(Date)
    runtime: Mapped[int | None] = mapped_column(Integer)
    file_tracked: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        """Return a concise representation of the Episode."""
        return (
            f"<Episode(show_id={self.show_id}, "
            f"s{self.season_number:02d}e{self.episode_number:02d}, "
            f"{self.name!r})>"
        )

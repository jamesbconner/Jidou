"""Episode model for TV show episodes."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class Episode(TimestampMixin, Base):
    """An individual TV show episode with TMDB metadata.

    Episodes are populated by the sync worker when it fetches season details
    from TMDB.  The ``file_tracked`` flag is set to ``True`` once a matching
    :class:`DownloadedFile` has been linked to this episode, and
    ``file_tracked_at`` records exactly when that transition occurred so
    activity dashboards can track intake volume over time regardless of
    whether the file arrived via SFTP download or path import.
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
    absolute_episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    still_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    file_tracked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        """Return a concise representation of the Episode."""
        return (
            f"<Episode(show_id={self.show_id}, "
            f"s{self.season_number:02d}e{self.episode_number:02d}, "
            f"{self.name!r})>"
        )

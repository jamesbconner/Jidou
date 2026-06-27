"""OrphanedTrackingRecord model for persisting unrecoverable episode tracking data."""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class OrphanedTrackingRecord(TimestampMixin, Base):
    """Tracks episode data that could not be migrated during a show rematch.

    Created by ``rematch_show`` when a tracked episode's ``(season_number,
    episode_number)`` key has no corresponding row in the new TMDB entry.
    The record persists in the Data Quality surface until the user manually
    resolves it by linking the filename to a specific episode.

    Two categories exist:
    - ``tracked_source="import"``: No DownloadedFile row; ``downloaded_file_id``
      is ``None``. Resolved by writing tracking fields directly to an Episode.
    - ``tracked_source="match"``: A DownloadedFile row exists with
      ``episode_id=NULL``; ``downloaded_file_id`` points to it. Resolved by
      patching the file with the correct ``episode_id``.
    """

    __tablename__ = "orphaned_tracking_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), index=True)
    tracked_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tracked_source: Mapped[str] = mapped_column(String(20))
    old_season_number: Mapped[int] = mapped_column(Integer)
    old_episode_number: Mapped[int] = mapped_column(Integer)
    downloaded_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("downloaded_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        """Return a concise representation."""
        return (
            f"<OrphanedTrackingRecord(show_id={self.show_id}, "
            f"S{self.old_season_number:02d}E{self.old_episode_number:02d}, "
            f"source={self.tracked_source!r})>"
        )

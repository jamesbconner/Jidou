"""DownloadedFile model for tracking SFTP-sourced media files."""

from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class FileStatus(StrEnum):
    """Lifecycle status of a downloaded file."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ROUTING = "routing"
    ROUTED = "routed"
    ERROR = "error"


class MatchedBy(StrEnum):
    """How the file was matched to a show/episode."""

    LLM = "llm"
    HEURISTIC = "heuristic"
    MANUAL = "manual"


class DownloadedFile(TimestampMixin, Base):
    """A media file tracked or downloaded from the remote SFTP server.

    ``show_id`` and ``episode_id`` are populated by the matching worker after
    the file has been linked to a specific show/episode.  Both are nullable
    because a file may exist before matching has run.

    ``file_size`` uses ``BigInteger`` to support files larger than 2 GiB.
    """

    __tablename__ = "downloaded_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(500))
    remote_path: Mapped[str] = mapped_column(String(1000))
    local_path: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[FileStatus] = mapped_column(
        SAEnum(FileStatus, values_callable=lambda e: [x.value for x in e]),
        default=FileStatus.PENDING,
        index=True,
    )
    matched_by: Mapped[MatchedBy | None] = mapped_column(
        SAEnum(MatchedBy, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        """Return a concise representation of the DownloadedFile."""
        return (
            f"<DownloadedFile(id={self.id}, "
            f"filename={self.original_filename!r}, "
            f"status={self.status})>"
        )

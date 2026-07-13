"""ScannedDirectory model for tracking remote directories already deep-walked."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


class ScannedDirectory(TimestampMixin, Base):
    """A remote directory ScanOrchestrator/SeedOrchestrator has fully deep-walked
    with no partial-failure or in-flight-upload risk.

    Purely a scan-layer "have I seen this path, completely" marker — no
    relationship to Show/Episode/DownloadedFile matching. Once a row exists for
    a remote_path, that directory is treated as permanently immutable and is
    never walked again: Jidou's SFTP sources are wide, flat, and single-use,
    so a directory known once stays known forever, with no mtime/staleness
    recheck needed.
    """

    __tablename__ = "scanned_directories"

    id: Mapped[int] = mapped_column(primary_key=True)
    remote_path: Mapped[str] = mapped_column(String(1000), unique=True)

    def __repr__(self) -> str:
        """Return a concise representation of the ScannedDirectory."""
        return f"<ScannedDirectory(remote_path={self.remote_path!r})>"

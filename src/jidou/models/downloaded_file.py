"""DownloadedFile model for tracking SFTP-sourced media files."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jidou.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from jidou.models.episode import Episode
    from jidou.models.show import Show


class FileStatus(StrEnum):
    """Lifecycle states for a downloaded media file.

    State machine::

        discovered ──► downloading ──► downloaded ──► matched ──► routing ──► routed
                                            │                         │
                                            └──► unmatched            └──► error
                                                     │
                                                     └──► matched  (manual/re-match)

        routed ──► matched  (Fix Eps reassignment; triggers re-routing)
        * ──► error         (any unexpected failure at any stage)

    Transitions:
        discovered  → downloading   Download task picks up the file.
        downloading → downloaded    Transfer complete; file is in staging.
        downloaded  → matched       Parse/match phase succeeds.
        downloaded  → unmatched     Parse/match phase finds no episode; needs manual review.
        unmatched   → matched       User resolves via UI, or match task re-runs successfully.
        matched     → routing       Route task starts moving the file.
        routing     → routed        File moved to its final library path.
        routing     → error         File move fails (permissions, path missing, etc.).
        routed      → matched       Fix Eps reassignment clears routing and re-queues.
        *           → error         Unexpected exception at any stage.

    Note:
        ``pending`` is a legacy value; new records use ``discovered`` instead.
    """

    DISCOVERED = "discovered"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    ROUTING = "routing"
    ROUTED = "routed"
    ERROR = "error"
    PENDING = "pending"  # legacy — replaced by DISCOVERED
    # Terminal state set by the one-time baseline seed operation.  No outbound
    # transitions; excluded from every pipeline orchestrator's status whitelist
    # and from the manual re-match allowlist in the files API.
    SEEDED = "seeded"


class MatchedBy(StrEnum):
    """How the file was matched to a show/episode."""

    LLM = "llm"
    HEURISTIC = "heuristic"
    MANUAL = "manual"


class DownloadedFile(TimestampMixin, Base):
    """A media file tracked or downloaded from the remote SFTP server.

    ``show_id`` and ``episode_id`` are NULL until the parse/match phase
    links the file to a specific show and episode.

    ``file_size`` uses ``BigInteger`` to support files larger than 2 GiB.

    Parsed fields (``parsed_*``) are populated by the parse orchestrator
    after the file has been downloaded to staging.
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
    remote_path: Mapped[str] = mapped_column(String(1000), unique=True)
    local_path: Mapped[str | None] = mapped_column(String(1000))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[FileStatus] = mapped_column(
        SAEnum(FileStatus, values_callable=lambda e: [x.value for x in e]),
        default=FileStatus.DISCOVERED,
        index=True,
    )
    matched_by: Mapped[MatchedBy | None] = mapped_column(
        SAEnum(MatchedBy, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    # Parsed metadata populated by the parse orchestrator
    parsed_show_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parsed_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsed_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_content_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships — use selectinload() in async queries; lazy="noload" prevents
    # accidental synchronous lazy-load (MissingGreenlet) if not explicitly loaded.
    show: Mapped[Show | None] = relationship("Show", foreign_keys=[show_id], lazy="noload")
    episode: Mapped[Episode | None] = relationship(
        "Episode", foreign_keys=[episode_id], lazy="noload"
    )

    def __repr__(self) -> str:
        """Return a concise representation of the DownloadedFile."""
        return (
            f"<DownloadedFile(id={self.id}, "
            f"filename={self.original_filename!r}, "
            f"status={self.status})>"
        )

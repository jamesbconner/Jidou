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
                                            │    │                    │
                                            │    └──► ignored         └──► error
                                            └──► unmatched
                                                     │    │
                                                     │    └──► ignored  (manual)
                                                     └──► matched  (manual/re-match)

        routed ──► matched  (Fix Eps reassignment; triggers re-routing)
        * ──► error         (any unexpected failure at any stage)
        * ──► missing ──► unmatched / matched  (local file vanishes, then reappears)

    Transitions:
        discovered  → downloading   Download task picks up the file.
        downloading → downloaded    Transfer complete; file is in staging.
        downloaded  → matched       Parse/match phase succeeds.
        downloaded  → unmatched     Parse/match phase finds no episode; needs manual review.
        downloaded  → ignored       Remote path fell under a configured noscan path;
                                     set immediately post-download, never enters parse/match.
        unmatched   → matched       User resolves via UI, or match task re-runs successfully.
        unmatched   → ignored       User manually excludes a stray non-media file from review.
        error       → ignored       User manually excludes a permanently broken row.
        matched     → routing       Route task starts moving the file.
        routing     → routed        File moved to its final library path.
        routing     → error         File move fails (permissions, path missing, etc.).
        routed      → matched       Fix Eps reassignment clears routing and re-queues.
        *           → error         Unexpected exception at any stage.
        *           → missing       ``local_path`` no longer exists on disk (e.g. renamed
                                     or moved outside the app) — detected during a
                                     Scan Local Files reconciliation pass; any settled
                                     status can transition here except the in-flight
                                     ones (discovered/downloading/pending/routing).
        missing     → unmatched     File reappears at the same path and had no episode.
        missing     → matched       File reappears at the same path and had an episode.

    Note:
        ``pending`` is a legacy value; new records use ``discovered`` instead.
        ``ignored`` is terminal — no outbound transitions.
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
    # Terminal state for files that are downloaded (so they're never re-fetched)
    # but deliberately excluded from parse/match/route — see IgnoredReason.
    IGNORED = "ignored"
    # Set when a Scan Local Files reconciliation pass finds local_path no
    # longer exists on disk (renamed/moved/deleted outside the app). Reverts
    # to unmatched/matched if a later pass finds the file back at the same
    # path — see services/file_reconciliation.py.
    MISSING = "missing"


class MatchedBy(StrEnum):
    """How the file was matched to a show/episode."""

    LLM = "llm"
    HEURISTIC = "heuristic"
    MANUAL = "manual"


class IgnoredReason(StrEnum):
    """Why a file was excluded from parse/match/route.

    Set at discovery time (``NOSCAN_PATH``) or via manual operator action
    (``MANUAL``); read by the download orchestrator to route the file
    straight to ``FileStatus.IGNORED`` instead of ``DOWNLOADED``.
    """

    NOSCAN_PATH = "noscan_path"
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
    # Three independently-sourced CRC32 readings (8-char uppercase hex), kept
    # separate so a mismatch can be pinpointed to a specific stage instead of
    # collapsed into one ambiguous value:
    #   crc32_extracted — cheap filename regex, read by DownloadOrchestrator
    #                      immediately after transfer; source of truth for
    #                      the corrupt-download check.
    #   crc32_declared  — parse_filename()'s own reading (LLM or heuristic),
    #                      persisted later by ParseOrchestrator; may diverge
    #                      from crc32_extracted if the LLM misreads the tag.
    #   crc32_computed  — actually computed from the downloaded bytes.
    crc32_extracted: Mapped[str | None] = mapped_column(String(8))
    crc32_declared: Mapped[str | None] = mapped_column(String(8))
    crc32_computed: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[FileStatus] = mapped_column(
        SAEnum(FileStatus, values_callable=lambda e: [x.value for x in e]),
        default=FileStatus.DISCOVERED,
        index=True,
    )
    matched_by: Mapped[MatchedBy | None] = mapped_column(
        SAEnum(MatchedBy, values_callable=lambda e: [x.value for x in e]),
        nullable=True,
    )
    # Set at discovery time for noscan-path files (before status even reaches
    # DOWNLOADED) so DownloadOrchestrator knows to route to IGNORED instead;
    # set directly to MANUAL by the manual-ignore API action.
    ignored_reason: Mapped[IgnoredReason | None] = mapped_column(
        SAEnum(IgnoredReason, values_callable=lambda e: [x.value for x in e]),
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

    @classmethod
    def new_from_remote(
        cls,
        *,
        name: str,
        remote_path: str,
        size: int,
        status: FileStatus,
        ignored_reason: IgnoredReason | None = None,
    ) -> DownloadedFile:
        """Build a not-yet-persisted row for a freshly discovered remote file.

        Shared by ``ScanOrchestrator`` (``status=DISCOVERED``) and
        ``SeedOrchestrator`` (``status=SEEDED``) — the only difference
        between how the two orchestrators record a newly-seen remote file.

        Args:
            name: Bare filename (``original_filename``).
            remote_path: Full remote path (unique key).
            size: File size in bytes.
            status: Initial lifecycle status.
            ignored_reason: Set by ``ScanOrchestrator`` when ``remote_path``
                falls under a configured noscan path, even though ``status``
                is still ``DISCOVERED`` — ``DownloadOrchestrator`` reads it
                after the transfer completes to route the file to
                ``IGNORED`` instead of ``DOWNLOADED``.

        Returns:
            A ``DownloadedFile`` instance, not yet added to any session.
        """
        return cls(
            show_id=None,
            original_filename=name,
            remote_path=remote_path,
            file_size=size,
            status=status,
            ignored_reason=ignored_reason,
        )

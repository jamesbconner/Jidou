"""SQLAlchemy models for RSS feed management (YaRSS2 / Deluge integration)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jidou.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from jidou.models.show import Show


class RssFeed(TimestampMixin, Base):
    """A YaRSS2 RSS feed source.

    Feeds can be imported from the remote config or created manually in Jidou.
    ``active=False`` feeds are excluded from the published config.
    """

    __tablename__ = "rss_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    remote_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    default_download_location: Mapped[str | None] = mapped_column(String(1024))
    default_move_completed: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Round-trips all other remote feed fields unchanged
    extra_config: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    subscriptions: Mapped[list[RssSubscription]] = relationship(
        "RssSubscription", back_populates="feed", lazy="raise"
    )

    def __repr__(self) -> str:
        """Return a concise representation of the RssFeed."""
        return f"<RssFeed(id={self.id}, remote_key={self.remote_key!r}, name={self.name!r})>"


class RssSubscription(TimestampMixin, Base):
    """A single YaRSS2 subscription (filter rule) for a show.

    Rows with ``remote_key=None`` are Jidou-created stubs that have never been
    published to the remote config.  ``enabled_in_config=False`` rows are
    excluded from the published config even after a key is assigned.
    """

    __tablename__ = "rss_subscriptions"
    __table_args__ = (
        # Partial unique index: remote_key must be unique but only when non-NULL
        Index(
            "uq_rss_subscriptions_remote_key",
            "remote_key",
            unique=True,
            postgresql_where="remote_key IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    remote_key: Mapped[str | None] = mapped_column(String(64), index=True)
    feed_id: Mapped[int | None] = mapped_column(
        ForeignKey("rss_feeds.id", ondelete="SET NULL"), index=True
    )
    show_id: Mapped[int | None] = mapped_column(
        ForeignKey("shows.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    regex_include: Mapped[str | None] = mapped_column(String(1024))
    regex_exclude: Mapped[str | None] = mapped_column(String(1024))
    regex_include_ignorecase: Mapped[bool] = mapped_column(Boolean, default=True)
    regex_exclude_ignorecase: Mapped[bool] = mapped_column(Boolean, default=True)
    # Per-subscription overrides; None means fall back to feed defaults
    download_location: Mapped[str | None] = mapped_column(String(1024))
    move_completed: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False = stub (never published); True = included in next publish
    enabled_in_config: Mapped[bool] = mapped_column(Boolean, default=False)
    label: Mapped[str | None] = mapped_column(String(255))
    last_match: Mapped[str | None] = mapped_column(String(512))
    # Round-trips all other remote subscription fields unchanged
    extra_config: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    feed: Mapped[RssFeed | None] = relationship(
        "RssFeed", back_populates="subscriptions", lazy="raise"
    )
    show: Mapped[Show | None] = relationship("Show", lazy="raise")

    def __repr__(self) -> str:
        """Return a concise representation of the RssSubscription."""
        return (
            f"<RssSubscription(id={self.id}, remote_key={self.remote_key!r}, "
            f"name={self.name!r}, enabled={self.enabled_in_config})>"
        )


class RssConfigSnapshot(TimestampMixin, Base):
    """A point-in-time snapshot of the raw remote YaRSS2 config file.

    Stored in raw text (not JSONB) because the format is non-standard:
    two concatenated JSON objects with no separator.
    """

    __tablename__ = "rss_config_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_type: Mapped[str] = mapped_column(String(32))  # "import" | "pre_publish"
    raw_content: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:
        """Return a concise representation of the RssConfigSnapshot."""
        return (
            f"<RssConfigSnapshot(id={self.id}, type={self.snapshot_type!r}, "
            f"len={len(self.raw_content)})>"
        )

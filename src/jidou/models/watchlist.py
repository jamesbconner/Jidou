"""Watchlist model for user-curated show collections."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jidou.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from jidou.models.show import Show


class WatchlistStatus(StrEnum):
    """Status of a watchlist entry."""

    PLANNED = "planned"
    WATCHING = "watching"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"


class WatchlistEntry(TimestampMixin, Base):
    """A user's watchlist entry tracking a specific show."""

    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("show_id", name="uq_watchlist_show_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"))
    status: Mapped[WatchlistStatus] = mapped_column(
        SAEnum(WatchlistStatus, values_callable=lambda e: [x.value for x in e]),
        default=WatchlistStatus.PLANNED,
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    position: Mapped[int] = mapped_column(default=0)

    show: Mapped[Show] = relationship("Show", lazy="raise")

    def __repr__(self) -> str:
        """Return a concise representation of the WatchlistEntry."""
        return f"<WatchlistEntry(id={self.id}, show_id={self.show_id}, status={self.status.value})>"

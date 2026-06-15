"""Watchlist model for user-curated show collections."""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from jidou.models.base import Base, TimestampMixin


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

    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"))
    status: Mapped[WatchlistStatus] = mapped_column(
        SAEnum(WatchlistStatus, values_callable=lambda e: [x.value for x in e]),
        default=WatchlistStatus.PLANNED,
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    position: Mapped[int] = mapped_column(default=0)

    def __repr__(self) -> str:
        """Return a concise representation of the WatchlistEntry."""
        return f"<WatchlistEntry(id={self.id}, show_id={self.show_id}, status={self.status.value})>"

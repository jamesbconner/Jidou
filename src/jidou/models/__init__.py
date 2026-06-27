"""SQLAlchemy model definitions."""

from jidou.models.base import Base, TimestampMixin
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.show import Show
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus

__all__ = [
    "BackgroundTask",
    "Base",
    "DownloadedFile",
    "Episode",
    "FileStatus",
    "MatchedBy",
    "OrphanedTrackingRecord",
    "Show",
    "TaskStatus",
    "TimestampMixin",
    "WatchlistEntry",
    "WatchlistStatus",
]

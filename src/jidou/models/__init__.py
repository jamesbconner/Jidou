"""SQLAlchemy model definitions."""

from jidou.models.app_setting import AppSetting
from jidou.models.base import Base, TimestampMixin
from jidou.models.downloaded_file import DownloadedFile, FileStatus, MatchedBy
from jidou.models.episode import Episode
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.rss import RssConfigSnapshot, RssFeed, RssSubscription
from jidou.models.show import Show
from jidou.models.task import BackgroundTask, TaskStatus
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus

__all__ = [
    "AppSetting",
    "BackgroundTask",
    "Base",
    "DownloadedFile",
    "Episode",
    "FileStatus",
    "MatchedBy",
    "OrphanedTrackingRecord",
    "RssConfigSnapshot",
    "RssFeed",
    "RssSubscription",
    "Show",
    "TaskStatus",
    "TimestampMixin",
    "WatchlistEntry",
    "WatchlistStatus",
]

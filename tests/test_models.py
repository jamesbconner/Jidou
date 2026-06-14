"""Tests for SQLAlchemy models."""

from jidou.models.show import Show
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus


def test_show_repr() -> None:
    """Test Show model string representation."""
    show = Show(id=1, tmdb_id=12345, title="Test Movie")
    assert "Test Movie" in repr(show)
    assert "12345" in repr(show)


def test_watchlist_entry_repr() -> None:
    """Test WatchlistEntry model string representation."""
    entry = WatchlistEntry(id=1, show_id=42, status=WatchlistStatus.WATCHING)
    assert "watching" in repr(entry).lower()
    assert "42" in repr(entry)


def test_watchlist_status_values() -> None:
    """Test that WatchlistStatus has expected values."""
    expected = {"planned", "watching", "completed", "dropped"}
    actual = {status.value for status in WatchlistStatus}
    assert actual == expected

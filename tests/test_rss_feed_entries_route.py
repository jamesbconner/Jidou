"""Tests for GET /api/rss/feeds/{feed_id}/entries."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.api.dependencies import get_feed_fetch_service
from jidou.database import get_session
from jidou.main import app
from jidou.models.rss import RssFeed
from jidou.models.show import Show
from jidou.services.feed_fetch import FeedEntry, FeedFetchError, FeedFetchResult

FEED_URL = "https://tracker.example/rss?passkey=SUPERSECRET"


def _entry(title: str) -> FeedEntry:
    return FeedEntry(title=title, guid=None, published=None)


def _feed() -> MagicMock:
    f = MagicMock(spec=RssFeed)
    f.id = 7
    f.url = FEED_URL
    return f


def _show(show_id: int = 42, title: str = "Show Name") -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = show_id
    s.title = title
    s.status = "Returning Series"
    s.poster_path = None
    return s


def _sub_row(
    sub_id: int,
    show_id: int | None = None,
    include: str | None = None,
    exclude: str | None = None,
) -> tuple[int, int | None, str | None, str | None, bool, bool]:
    """A row as selected by the route: id, show_id, include/exclude regex + ignorecase flags."""
    return (sub_id, show_id, include, exclude, True, True)


def _session(feed: MagicMock | None, sub_rows: list[tuple] | None = None):
    async def _mock_session():
        session = AsyncMock()
        feed_result = MagicMock()
        feed_result.scalar_one_or_none.return_value = feed
        subs_result = MagicMock()
        subs_result.all.return_value = sub_rows or []
        session.execute = AsyncMock(side_effect=[feed_result, subs_result])
        yield session

    return _mock_session


@pytest.fixture
def fetcher() -> Iterator[MagicMock]:
    svc = MagicMock()
    svc.fetch_entries = AsyncMock()
    app.dependency_overrides[get_feed_fetch_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_feed_fetch_service, None)
    app.dependency_overrides.pop(get_session, None)


def test_entries_404_when_feed_missing(fetcher: MagicMock) -> None:
    app.dependency_overrides[get_session] = _session(None)

    r = TestClient(app).get("/api/rss/feeds/7/entries")

    assert r.status_code == 404
    fetcher.fetch_entries.assert_not_called()


def test_entries_groups_annotates_library_and_existing_subscription(
    fetcher: MagicMock,
) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(
        entries=[
            _entry("Show.Name.S02E05.1080p-GRP"),
            _entry("Show.Name.S02E06.1080p-GRP"),
            _entry("Brand New Thing - 01"),
        ],
        malformed=True,
        cached=False,
    )
    app.dependency_overrides[get_session] = _session(_feed(), sub_rows=[_sub_row(99, show_id=42)])
    show = _show(42, "Show Name")

    async def _find(_session_, name: str, **_kw):
        return show if name == "Show Name" else None

    with patch("jidou.api.routes.rss.find_show_by_name", new=_find):
        r = TestClient(app).get("/api/rss/feeds/7/entries")

    assert r.status_code == 200
    body = r.json()
    assert body["feed_id"] == 7
    assert body["total_entries"] == 3
    assert body["malformed"] is True
    assert body["cached"] is False
    by_name = {g["parsed_name"]: g for g in body["groups"]}
    known = by_name["Show Name"]
    assert known["entry_count"] == 2
    assert known["season_min"] == 2 and known["episode_max"] == 6
    assert known["library_show"]["id"] == 42
    assert known["existing_subscription_id"] == 99
    new = by_name["Brand New Thing"]
    assert new["library_show"] is None
    assert new["existing_subscription_id"] is None


def test_entries_in_library_without_subscription(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(
        entries=[_entry("Show Name - 01")], malformed=False, cached=True
    )
    app.dependency_overrides[get_session] = _session(_feed(), sub_rows=[])

    with patch("jidou.api.routes.rss.find_show_by_name", new=AsyncMock(return_value=_show(42))):
        r = TestClient(app).get("/api/rss/feeds/7/entries")

    group = r.json()["groups"][0]
    assert group["library_show"]["id"] == 42
    assert group["existing_subscription_id"] is None
    assert r.json()["cached"] is True


def test_entries_refresh_flag_bypasses_cache(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(entries=[], malformed=False, cached=False)
    app.dependency_overrides[get_session] = _session(_feed())

    r = TestClient(app).get("/api/rss/feeds/7/entries?refresh=true")

    assert r.status_code == 200
    assert r.json()["groups"] == []
    fetcher.fetch_entries.assert_awaited_once_with(FEED_URL, bypass_cache=True)


def test_entries_default_uses_cache(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(entries=[], malformed=False, cached=True)
    app.dependency_overrides[get_session] = _session(_feed())

    TestClient(app).get("/api/rss/feeds/7/entries")

    fetcher.fetch_entries.assert_awaited_once_with(FEED_URL, bypass_cache=False)


def test_entries_fetch_failure_is_502_without_secret(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.side_effect = FeedFetchError("Feed server returned HTTP 403")
    app.dependency_overrides[get_session] = _session(_feed())

    r = TestClient(app).get("/api/rss/feeds/7/entries")

    assert r.status_code == 502
    assert r.json()["detail"] == "Feed server returned HTTP 403"
    assert "SUPERSECRET" not in r.text


def test_entries_timeout_is_504(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.side_effect = FeedFetchError("Timed out fetching feed", timed_out=True)
    app.dependency_overrides[get_session] = _session(_feed())

    r = TestClient(app).get("/api/rss/feeds/7/entries")

    assert r.status_code == 504


def test_entries_slash_titled_show_is_looked_up_by_its_exact_name(fetcher: MagicMock) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(
        entries=[_entry("[Grp] Fate/stay night - 05 (1080p).mkv")], malformed=False, cached=False
    )
    app.dependency_overrides[get_session] = _session(_feed(), sub_rows=[])
    looked_up: list[str] = []

    async def _find(_session_, name: str, **_kw):
        looked_up.append(name)
        return _show(11, "Fate/stay night")

    with patch("jidou.api.routes.rss.find_show_by_name", new=_find):
        r = TestClient(app).get("/api/rss/feeds/7/entries")

    assert looked_up == ["Fate/stay night"]
    group = r.json()["groups"][0]
    assert group["parsed_name"] == "Fate/stay night"
    assert group["library_show"]["id"] == 11


def test_entries_tracker_titled_group_is_subscribed_via_regex_without_library_link(
    fetcher: MagicMock,
) -> None:
    """Regression: parsed names that miss the library must not hide a subscription."""
    fetcher.fetch_entries.return_value = FeedFetchResult(
        entries=[
            _entry(
                "Example Show - TV Series [2026] :: Web | MKV | h264 | 1080p | AAC 2.0 | "
                "Softsubs (Group) | Episode 3 | Freeleech"
            ),
            _entry("Unwatched Show - TV Series [2026] :: Web | MKV | h264 | 1080p | Episode 1"),
        ],
        malformed=False,
        cached=False,
    )
    app.dependency_overrides[get_session] = _session(
        _feed(), sub_rows=[_sub_row(55, show_id=None, include=r"^Example.Show.*1080p")]
    )

    with patch("jidou.api.routes.rss.find_show_by_name", new=AsyncMock(return_value=None)):
        r = TestClient(app).get("/api/rss/feeds/7/entries")

    by_name = {g["parsed_name"]: g for g in r.json()["groups"]}
    assert by_name["Example Show"]["library_show"] is None
    assert by_name["Example Show"]["existing_subscription_id"] == 55
    assert by_name["Unwatched Show"]["existing_subscription_id"] is None


def test_entries_subscription_query_only_considers_active_published_rules(
    fetcher: MagicMock,
) -> None:
    fetcher.fetch_entries.return_value = FeedFetchResult(entries=[], malformed=False, cached=False)
    session = AsyncMock()
    feed_result = MagicMock()
    feed_result.scalar_one_or_none.return_value = _feed()
    subs_result = MagicMock()
    subs_result.all.return_value = []
    session.execute = AsyncMock(side_effect=[feed_result, subs_result])

    async def _mock_session():
        yield session

    app.dependency_overrides[get_session] = _mock_session

    TestClient(app).get("/api/rss/feeds/7/entries")

    sql = str(session.execute.await_args_list[1].args[0].compile()).lower()
    assert "active" in sql
    assert "enabled_in_config" in sql

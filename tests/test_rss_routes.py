"""Tests for the /api/rss/* API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.rss import RssFeed, RssSubscription
from jidou.models.show import Show

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _make_show(*, id: int = 1) -> MagicMock:
    s = MagicMock(spec=Show)
    s.id = id
    s.title = f"Test Show {id}"
    return s


def _make_feed(
    *,
    id: int = 1,
    remote_key: str | None = "0",
    name: str = "ShowRSS",
    url: str = "https://showrss.info/feed",
) -> MagicMock:
    f = MagicMock(spec=RssFeed)
    f.id = id
    f.remote_key = remote_key
    f.name = name
    f.url = url
    f.default_download_location = None
    f.default_move_completed = None
    f.extra_config = None
    f.created_at = _now()
    f.updated_at = _now()
    return f


def _make_sub(
    *,
    id: int = 1,
    remote_key: str | None = "0",
    name: str = "Test Show",
    feed_id: int | None = 1,
    show_id: int | None = None,
    enabled_in_config: bool = False,
    active: bool = True,
) -> MagicMock:
    s = MagicMock(spec=RssSubscription)
    s.id = id
    s.remote_key = remote_key
    s.name = name
    s.feed_id = feed_id
    s.show_id = show_id
    s.regex_include = None
    s.regex_exclude = None
    s.regex_include_ignorecase = True
    s.regex_exclude_ignorecase = True
    s.download_location = None
    s.move_completed = None
    s.active = active
    s.enabled_in_config = enabled_in_config
    s.label = None
    s.last_match = None
    s.extra_config = None
    s.feed = _make_feed() if feed_id else None
    s.show = None
    s.created_at = _now()
    s.updated_at = _now()
    return s


def _session_override(
    single: MagicMock | None = None,
    many: list[MagicMock] | None = None,
    execute_side_effect: list[MagicMock] | None = None,
) -> "type[AsyncMock]":
    """Build a mock async session factory."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()

        if execute_side_effect is not None:
            session.execute = AsyncMock(side_effect=execute_side_effect)
        else:
            result = MagicMock()
            result.scalar_one_or_none.return_value = single
            result.scalar_one.return_value = single
            result.scalars.return_value.all.return_value = many or ([single] if single else [])
            session.execute = AsyncMock(return_value=result)

        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/rss/feeds
# ---------------------------------------------------------------------------


def test_list_feeds_empty() -> None:
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        r = TestClient(app).get("/api/rss/feeds")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_feeds_returns_records() -> None:
    from jidou.database import get_session

    feed = _make_feed()
    app.dependency_overrides[get_session] = _session_override(many=[feed])
    try:
        r = TestClient(app).get("/api/rss/feeds")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == 1
        assert data[0]["name"] == "ShowRSS"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/rss/feeds
# ---------------------------------------------------------------------------


def test_create_feed_returns_201() -> None:
    from jidou.database import get_session

    feed = _make_feed(id=5)

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        async def _refresh(obj: object, attrs: object = None) -> None:
            obj.id = 5  # type: ignore[union-attr]
            obj.remote_key = "0"  # type: ignore[union-attr]
            obj.name = "ShowRSS"  # type: ignore[union-attr]
            obj.url = "https://showrss.info/feed"  # type: ignore[union-attr]
            obj.default_download_location = None  # type: ignore[union-attr]
            obj.default_move_completed = None  # type: ignore[union-attr]
            obj.extra_config = None  # type: ignore[union-attr]
            obj.created_at = feed.created_at  # type: ignore[union-attr]
            obj.updated_at = feed.updated_at  # type: ignore[union-attr]

        session.refresh = AsyncMock(side_effect=_refresh)
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        r = TestClient(app).post(
            "/api/rss/feeds",
            json={"name": "ShowRSS", "url": "https://showrss.info/feed"},
        )
        assert r.status_code == 201
        assert r.json()["name"] == "ShowRSS"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /api/rss/feeds/{id}
# ---------------------------------------------------------------------------


def test_update_feed_returns_200() -> None:
    from jidou.database import get_session

    feed = _make_feed()

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.flush = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = feed
        session.execute = AsyncMock(return_value=result)

        async def _refresh(obj: object, attrs: object = None) -> None:
            pass

        session.refresh = AsyncMock(side_effect=_refresh)
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        r = TestClient(app).patch("/api/rss/feeds/1", json={"name": "Updated"})
        assert r.status_code == 200
        assert feed.name == "Updated"
    finally:
        app.dependency_overrides.clear()


def test_update_feed_404() -> None:
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        r = TestClient(app).patch("/api/rss/feeds/999", json={"name": "X"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/rss/feeds/{id}
# ---------------------------------------------------------------------------


def test_delete_feed_404() -> None:
    from jidou.database import get_session

    # First execute returns None (feed not found)
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    app.dependency_overrides[get_session] = _session_override(execute_side_effect=[not_found])
    try:
        r = TestClient(app).delete("/api/rss/feeds/999")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_delete_feed_blocked_by_subscription() -> None:
    from jidou.database import get_session

    feed = _make_feed()
    sub = _make_sub()

    feed_result = MagicMock()
    feed_result.scalar_one_or_none.return_value = feed
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub  # subscription exists → block

    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[feed_result, sub_result]
    )
    try:
        r = TestClient(app).delete("/api/rss/feeds/1")
        assert r.status_code == 400
        assert "subscriptions" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_delete_feed_success() -> None:
    from jidou.database import get_session

    feed = _make_feed()
    feed_result = MagicMock()
    feed_result.scalar_one_or_none.return_value = feed
    no_subs = MagicMock()
    no_subs.scalar_one_or_none.return_value = None  # no subscriptions

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        session.execute = AsyncMock(side_effect=[feed_result, no_subs])
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        r = TestClient(app).delete("/api/rss/feeds/1")
        assert r.status_code == 204
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/rss/subscriptions
# ---------------------------------------------------------------------------


def test_list_subscriptions_empty() -> None:
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(many=[])
    try:
        r = TestClient(app).get("/api/rss/subscriptions")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_subscriptions_returns_records() -> None:
    from jidou.database import get_session

    sub = _make_sub()
    app.dependency_overrides[get_session] = _session_override(many=[sub])
    try:
        r = TestClient(app).get("/api/rss/subscriptions")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Show"
    finally:
        app.dependency_overrides.clear()


def test_list_subscriptions_enabled_only_filter() -> None:
    from jidou.database import get_session

    sub = _make_sub(enabled_in_config=True)
    app.dependency_overrides[get_session] = _session_override(many=[sub])
    try:
        r = TestClient(app).get("/api/rss/subscriptions?enabled_only=true")
        assert r.status_code == 200
        assert r.json()[0]["enabled_in_config"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/rss/subscriptions/{id}
# ---------------------------------------------------------------------------


def test_get_subscription_found() -> None:
    from jidou.database import get_session

    sub = _make_sub()
    app.dependency_overrides[get_session] = _session_override(single=sub)
    try:
        r = TestClient(app).get("/api/rss/subscriptions/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1
    finally:
        app.dependency_overrides.clear()


def test_get_subscription_404() -> None:
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        r = TestClient(app).get("/api/rss/subscriptions/999")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PATCH /api/rss/subscriptions/{id}
# ---------------------------------------------------------------------------


def test_update_subscription_404() -> None:
    from jidou.database import get_session

    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    app.dependency_overrides[get_session] = _session_override(execute_side_effect=[not_found])
    try:
        r = TestClient(app).patch("/api/rss/subscriptions/999", json={"name": "X"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_subscription_returns_200() -> None:
    from jidou.database import get_session

    sub = _make_sub()
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub
    sub_result.scalar_one.return_value = sub
    # First execute: fetch sub; second execute: re-fetch with selectinload
    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[sub_result, sub_result]
    )
    try:
        r = TestClient(app).patch(
            "/api/rss/subscriptions/1",
            json={"regex_include": ".*1080p.*"},
        )
        assert r.status_code == 200
        assert sub.regex_include == ".*1080p.*"
    finally:
        app.dependency_overrides.clear()


def test_update_subscription_bad_feed_id() -> None:
    from jidou.database import get_session

    sub = _make_sub()
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub
    feed_not_found = MagicMock()
    feed_not_found.scalar_one_or_none.return_value = None

    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[sub_result, feed_not_found]
    )
    try:
        r = TestClient(app).patch("/api/rss/subscriptions/1", json={"feed_id": 99})
        assert r.status_code == 404
        assert "feed" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/rss/subscriptions/{id}
# ---------------------------------------------------------------------------


def test_delete_subscription_404() -> None:
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(single=None)
    try:
        r = TestClient(app).delete("/api/rss/subscriptions/999")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_delete_subscription_blocked_when_enabled() -> None:
    from jidou.database import get_session

    sub = _make_sub(enabled_in_config=True)
    app.dependency_overrides[get_session] = _session_override(single=sub)
    try:
        r = TestClient(app).delete("/api/rss/subscriptions/1")
        assert r.status_code == 400
        assert "enabled_in_config" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_delete_subscription_success() -> None:
    from jidou.database import get_session

    sub = _make_sub(enabled_in_config=False)

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.delete = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = sub
        session.execute = AsyncMock(return_value=result)
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        r = TestClient(app).delete("/api/rss/subscriptions/1")
        assert r.status_code == 204
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# show_id validation (Bugbot fix)
# ---------------------------------------------------------------------------


def test_create_subscription_bad_show_id_returns_404() -> None:
    """A non-existent show_id on create returns 404, not 500."""
    from jidou.database import get_session

    feed = _make_feed()
    feed_result = MagicMock()
    feed_result.scalar_one_or_none.return_value = feed
    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None

    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[feed_result, show_not_found]
    )
    try:
        r = TestClient(app).post(
            "/api/rss/subscriptions",
            json={"name": "Test", "feed_id": 1, "show_id": 999},
        )
        assert r.status_code == 404
        assert "Show" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_update_subscription_bad_show_id_returns_404() -> None:
    """A non-existent show_id on update returns 404, not 500."""
    from jidou.database import get_session

    sub = _make_sub()
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = sub
    show_not_found = MagicMock()
    show_not_found.scalar_one_or_none.return_value = None

    app.dependency_overrides[get_session] = _session_override(
        execute_side_effect=[sub_result, show_not_found]
    )
    try:
        r = TestClient(app).patch("/api/rss/subscriptions/1", json={"show_id": 999})
        assert r.status_code == 404
        assert "Show" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()

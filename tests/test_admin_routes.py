"""Tests for the /admin API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app


class _FakePipeline:
    """Minimal fake of a redis.asyncio pipeline, backed by the parent FakeRedis dicts."""

    def __init__(self, parent: "_FakeRedis") -> None:
        self._parent = parent
        self._ops: list[tuple[str, tuple, dict]] = []

    def set(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("set", args, kwargs))

    def zadd(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("zadd", args, kwargs))

    def delete(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("delete", args, kwargs))

    async def execute(self) -> list[object]:
        for op, args, _kwargs in self._ops:
            if op == "set":
                self._parent._store[args[0]] = args[1]
            elif op == "zadd":
                self._parent._zset.update(args[1])
            elif op == "delete":
                for key in args:
                    self._parent._store.pop(key, None)
        self._ops.clear()
        return []


class _FakeRedis:
    """In-memory fake of the subset of redis.asyncio.Redis CacheBackend uses."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._zset: dict[str, float] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(k) for k in keys]

    async def scan(self, cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        prefix = match.rstrip("*")
        return 0, [k for k in self._store if k.startswith(prefix)]

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                deleted += 1
            self._zset.pop(key, None)
        return deleted

    async def zcard(self, key: str) -> int:
        return len(self._zset)

    async def zpopmin(self, key: str, count: int) -> list[tuple[str, float]]:
        return []

    async def aclose(self) -> None:
        pass


def _session_override_with_scalars(values: list[int]) -> "type[AsyncMock]":
    """Return a session override whose scalar() calls return values in order."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        session.scalar = AsyncMock(side_effect=values)
        # execute() still needed by health checks
        result = MagicMock()
        result.scalar_one.return_value = 1
        session.execute = AsyncMock(return_value=result)
        yield session

    return _mock_session  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# GET /api/admin/stats
# ---------------------------------------------------------------------------


def test_get_stats_returns_table_counts() -> None:
    """GET /api/admin/stats returns dashboard stat fields."""
    from jidou.database import get_session

    # scalar() call order: episodes_tracked, episodes_total, files_needs_attention,
    # files_added_1d, files_added_7d, files_added_30d, shows, watchlist, background_tasks,
    # dq_no_path, dq_no_content_type, dq_no_episodes, dq_orphan, dq_total
    app.dependency_overrides[get_session] = _session_override_with_scalars(
        [6, 369, 2, 1, 5, 12, 3, 4, 7, 1, 2, 1, 0, 3]
    )
    try:
        response = TestClient(app).get("/api/admin/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["shows"] == 3
        assert body["episodes_tracked"] == 6
        assert body["episodes_total"] == 369
        assert body["files_needs_attention"] == 2
        assert body["files_added_1d"] == 1
        assert body["files_added_7d"] == 5
        assert body["files_added_30d"] == 12
        assert body["watchlist"] == 4
        assert body["background_tasks"] == 7
        assert body["dq_no_path"] == 1
        assert body["dq_no_content_type"] == 2
        assert body["dq_no_episodes"] == 1
        assert body["dq_orphan"] == 0
        assert body["dq_total"] == 3
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/admin/cache/flush
# ---------------------------------------------------------------------------


def test_flush_cache_returns_ok_and_count() -> None:
    """POST /api/admin/cache/flush clears the Redis-backed cache."""
    with patch("redis.asyncio.from_url", return_value=_FakeRedis()):
        response = TestClient(app).post("/api/admin/cache/flush")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert isinstance(body["cleared"], int)


@pytest.mark.asyncio
async def test_flush_cache_cleared_count_matches_populated_cache() -> None:
    """Flushing a cache with N items reports cleared=N."""
    from jidou.services.cache import cache

    fake_redis = _FakeRedis()
    with patch("redis.asyncio.from_url", return_value=fake_redis):
        # Populate the cache with 2 known entries
        await cache.set("k1", "v1")
        await cache.set("k2", "v2")

        response = TestClient(app).post("/api/admin/cache/flush")
        body = response.json()
        assert body["ok"] is True
        assert body["cleared"] == 2
        # After flush the cache should be empty
        assert await cache.get("k1") is None


# ---------------------------------------------------------------------------
# GET /api/admin/health
# ---------------------------------------------------------------------------


def test_health_returns_healthy_true_when_all_pass() -> None:
    """GET /api/admin/health reports healthy=True when DB and Redis pass."""
    from jidou.database import get_session

    async def _ok_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one.return_value = 1
        session.execute = AsyncMock(return_value=result)
        yield session

    mock_r = AsyncMock()
    mock_r.ping = AsyncMock()
    mock_r.aclose = AsyncMock()

    app.dependency_overrides[get_session] = _ok_session
    try:
        with (
            patch("jidou.api.routes.admin.settings") as mock_settings,
            patch("redis.asyncio.from_url", return_value=mock_r),
        ):
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.tmdb_api_key = "set"
            response = TestClient(app).get("/api/admin/health")
        assert response.status_code == 200
        body = response.json()
        assert "healthy" in body
        assert "services" in body
    finally:
        app.dependency_overrides.clear()


def test_health_returns_healthy_false_when_db_fails() -> None:
    """GET /api/admin/health reports healthy=False when DB is unreachable."""
    from jidou.database import get_session

    async def _failing_session() -> AsyncMock:
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=ConnectionRefusedError("db down"))
        yield session

    app.dependency_overrides[get_session] = _failing_session
    try:
        with patch("jidou.api.routes.admin.settings") as mock_settings:
            mock_settings.redis_url = ""
            mock_settings.tmdb_api_key = None
            response = TestClient(app).get("/api/admin/health")
        assert response.status_code == 200
        body = response.json()
        assert body["healthy"] is False
        assert body["services"]["database"]["ok"] is False
    finally:
        app.dependency_overrides.clear()


def test_health_redis_not_configured_does_not_make_unhealthy() -> None:
    """GET /api/admin/health must not report unhealthy just because REDIS_URL is unset."""
    from jidou.database import get_session

    async def _ok_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one.return_value = 1
        session.execute = AsyncMock(return_value=result)
        yield session

    app.dependency_overrides[get_session] = _ok_session
    try:
        with patch("jidou.api.routes.admin.settings") as mock_settings:
            mock_settings.redis_url = ""
            mock_settings.tmdb_api_key = "set"
            response = TestClient(app).get("/api/admin/health")
        assert response.status_code == 200
        body = response.json()
        # Redis not configured is not a failure
        assert body["services"]["redis"]["ok"] is True
        assert body["services"]["redis"]["configured"] is False
        # Overall health should not be dragged down by unconfigured optional Redis
        assert body["healthy"] is True
    finally:
        app.dependency_overrides.clear()

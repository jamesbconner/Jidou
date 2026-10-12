"""Characterization tests pinning both health endpoints' probe behaviour.

These guard the shared-probe refactor: response shapes, error messages, probe
order, and exactly what each probe touches must not change.
"""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app

_ADMIN = "/api/admin/health"
_PUBLIC = "/api/health"


def _redis_mock(ping_error: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    client.ping = AsyncMock(side_effect=ping_error) if ping_error else AsyncMock()
    client.aclose = AsyncMock()
    return client


def _celery_mock(pong: Any = None, error: Exception | None = None) -> MagicMock:
    celery = MagicMock()
    ping = celery.control.inspect.return_value.ping
    if error:
        ping.side_effect = error
    else:
        ping.return_value = pong
    return celery


def _configure(settings: MagicMock, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "redis_url": "redis://localhost:6379/0",
        "tmdb_api_key": "key",
        "sftp_host": "sftp.example.com",
        "llm_provider": "none",
        "llm_model": "",
    }
    values.update(overrides)
    for name, value in values.items():
        setattr(settings, name, value)


@pytest.fixture
def session_factory() -> Iterator[Callable[[AsyncMock], None]]:
    """Install a DB session override; cleared after the test."""

    def install(session: AsyncMock) -> None:
        async def override() -> Any:
            yield session

        app.dependency_overrides[get_session] = override

    yield install
    app.dependency_overrides.clear()


def _ok_session(version: str | None = "rev1") -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = version
    session.execute = AsyncMock(return_value=result)
    return session


def _get_admin(
    session: AsyncMock,
    install: Callable[[AsyncMock], None],
    *,
    celery: MagicMock | None = None,
    redis_client: AsyncMock | None = None,
    **settings_overrides: Any,
) -> tuple[dict[str, Any], MagicMock]:
    install(session)
    from_url = MagicMock(return_value=redis_client or _redis_mock())
    with (
        patch("jidou.api.routes.admin.settings") as mock_settings,
        patch("redis.asyncio.from_url", from_url),
        patch("jidou.api.routes.admin.celery_app", celery or _celery_mock({"w1@h": {}})),
    ):
        _configure(mock_settings, **settings_overrides)
        response = TestClient(app).get(_ADMIN)
    assert response.status_code == 200
    return response.json(), from_url


# ---------------------------------------------------------------------------
# GET /api/admin/health
# ---------------------------------------------------------------------------


def test_admin_all_services_exact_shape(session_factory: Callable[[AsyncMock], None]) -> None:
    body, from_url = _get_admin(_ok_session("rev1"), session_factory)
    services = body["services"]
    assert list(services) == ["database", "redis", "celery", "tmdb", "sftp", "llm"]
    assert set(services["database"]) == {"ok", "latency_ms", "alembic_version"}
    assert services["database"]["ok"] is True
    assert services["database"]["alembic_version"] == "rev1"
    assert isinstance(services["database"]["latency_ms"], float)
    assert set(services["redis"]) == {"ok", "latency_ms"}
    assert services["redis"]["ok"] is True
    assert set(services["celery"]) == {"ok", "latency_ms", "workers"}
    assert services["celery"]["workers"] == ["w1@h"]
    assert services["tmdb"] == {"ok": True, "configured": True}
    assert services["sftp"] == {"ok": True, "configured": True}
    assert services["llm"] == {"ok": True, "configured": False, "error": "not configured"}
    assert body["healthy"] is True
    # Raw (bytes) client; passing decode_responses=False explicitly is equivalent.
    from_url.assert_called_once()
    assert from_url.call_args.args == ("redis://localhost:6379/0",)
    assert from_url.call_args.kwargs.get("decode_responses", False) is False


def test_admin_database_failure_reports_error_and_no_alembic_key(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    body, _ = _get_admin(session, session_factory)
    db = body["services"]["database"]
    assert set(db) == {"ok", "latency_ms", "error"}
    assert db["ok"] is False
    assert db["error"] == "db down"
    assert body["healthy"] is False


def test_admin_alembic_lookup_failure_rolls_back_and_stays_ok(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    session = AsyncMock()
    ok = MagicMock()
    session.execute = AsyncMock(side_effect=[ok, RuntimeError("no table")])
    body, _ = _get_admin(session, session_factory)
    db = body["services"]["database"]
    assert db["ok"] is True
    assert db["alembic_version"] is None
    session.rollback.assert_awaited_once()
    assert session.execute.await_count == 2


def test_admin_redis_ping_failure_reports_error_and_closes(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    client = _redis_mock(ConnectionError("refused"))
    body, _ = _get_admin(_ok_session(), session_factory, redis_client=client)
    redis = body["services"]["redis"]
    assert set(redis) == {"ok", "latency_ms", "error"}
    assert redis["ok"] is False
    assert redis["error"] == "refused"
    assert body["healthy"] is False
    client.aclose.assert_awaited_once()


def test_admin_redis_client_creation_failure_reports_error(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    session_factory(_ok_session())
    with (
        patch("jidou.api.routes.admin.settings") as mock_settings,
        patch("redis.asyncio.from_url", side_effect=OSError("cannot connect")),
        patch("jidou.api.routes.admin.celery_app", _celery_mock({"w": {}})),
    ):
        _configure(mock_settings)
        body = TestClient(app).get(_ADMIN).json()
    assert body["services"]["redis"]["ok"] is False
    assert body["services"]["redis"]["error"] == "cannot connect"


def test_admin_redis_unconfigured_makes_no_connection(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    body, from_url = _get_admin(_ok_session(), session_factory, redis_url="")
    assert body["services"]["redis"] == {"ok": True, "configured": False}
    assert body["healthy"] is True
    from_url.assert_not_called()


def test_admin_celery_pinged_with_two_second_timeout(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    celery = _celery_mock({"a@h": {}, "b@h": {}})
    body, _ = _get_admin(_ok_session(), session_factory, celery=celery)
    celery.control.inspect.assert_called_once_with(timeout=2.0)
    assert body["services"]["celery"]["workers"] == ["a@h", "b@h"]


def test_admin_celery_no_workers_error_shape(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    body, _ = _get_admin(_ok_session(), session_factory, celery=_celery_mock(None))
    celery = body["services"]["celery"]
    assert set(celery) == {"ok", "latency_ms", "error"}
    assert celery["error"] == "No Celery workers responded to ping"
    assert body["healthy"] is False


def test_admin_celery_timeout_exception_message_reported(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    body, _ = _get_admin(
        _ok_session(), session_factory, celery=_celery_mock(error=TimeoutError("broker timeout"))
    )
    celery = body["services"]["celery"]
    assert celery["ok"] is False
    assert celery["error"] == "broker timeout"
    assert set(celery) == {"ok", "latency_ms", "error"}


def test_admin_missing_tmdb_and_sftp_config(
    session_factory: Callable[[AsyncMock], None],
) -> None:
    body, _ = _get_admin(_ok_session(), session_factory, tmdb_api_key="", sftp_host="")
    services = body["services"]
    assert services["tmdb"] == {
        "ok": False,
        "configured": False,
        "error": "TMDB_API_KEY not set",
    }
    assert services["sftp"] == {"ok": False, "configured": False, "error": "SFTP_HOST not set"}
    assert body["healthy"] is False


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        (
            "openai",
            "gpt-x",
            {"ok": True, "configured": True, "provider": "openai", "model": "gpt-x"},
        ),
        ("openai", "", {"ok": True, "configured": False, "error": "LLM_MODEL not set"}),
        ("NONE", "gpt-x", {"ok": True, "configured": False, "error": "not configured"}),
        ("none", "", {"ok": True, "configured": False, "error": "not configured"}),
    ],
)
def test_admin_llm_config_states(
    session_factory: Callable[[AsyncMock], None],
    provider: str,
    model: str,
    expected: dict[str, Any],
) -> None:
    body, _ = _get_admin(_ok_session(), session_factory, llm_provider=provider, llm_model=model)
    assert body["services"]["llm"] == expected


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------


def _engine_mock(error: Exception | None = None) -> MagicMock:
    conn = AsyncMock()
    if error:
        conn.execute = AsyncMock(side_effect=error)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = ctx
    return engine


def _get_public(
    engine: MagicMock, redis_patch: Any, **settings_overrides: Any
) -> tuple[Any, MagicMock]:
    with (
        patch("jidou.api.health.engine", engine),
        patch("jidou.api.health.settings") as mock_settings,
        redis_patch as from_url,
    ):
        _configure(mock_settings, **settings_overrides)
        with TestClient(app) as client:
            return client.get(_PUBLIC), from_url


def test_public_all_healthy_exact_body() -> None:
    client = _redis_mock()
    response, from_url = _get_public(
        _engine_mock(), patch("redis.asyncio.from_url", return_value=client)
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "healthy"
    assert body["services"] == {
        "postgres": {"status": "healthy"},
        "redis": {"status": "healthy"},
        "tmdb": {"status": "configured"},
        "sftp": {"status": "configured"},
    }
    assert set(body) == {"status", "version", "timestamp", "services"}
    # decode_responses=True is how this endpoint has always connected.
    from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)
    client.ping.assert_awaited_once()
    client.aclose.assert_awaited_once()


def test_public_postgres_failure_is_503_with_error() -> None:
    response, _ = _get_public(
        _engine_mock(RuntimeError("pg down")),
        patch("redis.asyncio.from_url", return_value=_redis_mock()),
    )
    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["services"]["postgres"] == {"status": "unhealthy", "error": "pg down"}
    assert body["services"]["redis"] == {"status": "healthy"}


def test_public_redis_ping_failure_is_503_and_closes() -> None:
    client = _redis_mock(ConnectionError("Redis unreachable"))
    response, _ = _get_public(_engine_mock(), patch("redis.asyncio.from_url", return_value=client))
    body = response.json()
    assert response.status_code == 503
    assert body["services"]["redis"] == {"status": "unhealthy", "error": "Redis unreachable"}
    assert body["services"]["postgres"] == {"status": "healthy"}
    client.aclose.assert_awaited_once()


def test_public_redis_creation_failure_is_503() -> None:
    response, _ = _get_public(
        _engine_mock(), patch("redis.asyncio.from_url", side_effect=OSError("Cannot connect"))
    )
    assert response.status_code == 503
    assert response.json()["services"]["redis"] == {
        "status": "unhealthy",
        "error": "Cannot connect",
    }


def test_public_unconfigured_tmdb_sftp_do_not_degrade() -> None:
    response, _ = _get_public(
        _engine_mock(),
        patch("redis.asyncio.from_url", return_value=_redis_mock()),
        tmdb_api_key="",
        sftp_host="",
    )
    body = response.json()
    assert response.status_code == 200
    assert body["services"]["tmdb"] == {"status": "not-configured"}
    assert body["services"]["sftp"] == {"status": "not-configured"}


def test_public_probe_order_postgres_before_redis() -> None:
    order: list[str] = []
    engine = _engine_mock()
    ctx = engine.connect.return_value

    def connect() -> Any:
        order.append("pg")
        return ctx

    engine.connect.side_effect = connect
    client = _redis_mock()
    client.ping = AsyncMock(side_effect=lambda: order.append("redis"))
    _get_public(engine, patch("redis.asyncio.from_url", return_value=client))
    assert order == ["pg", "redis"]

"""Tests for the RSS import orchestrator and POST /api/rss/import endpoint."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.orchestrators.rss_import_orchestrator import RssImportOrchestrator
from jidou.services.sftp_service import SFTPService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_HEADER = {"file": 1, "format": 1}
_BODY = {
    "rssfeeds": {
        "0": {"name": "ShowRSS", "url": "https://showrss.info/user/123.rss", "active": True}
    },
    "subscriptions": {
        "0": {
            "name": "The Last of Us",
            "active": True,
            "last_match": "2026-06-01",
            "regex_include": ".*1080p.*",
        },
        "1": {"name": "Severance", "active": True, "last_match": None},
    },
    "cookies": {},
    "email_messages": {},
}

_RAW = json.dumps(_HEADER, separators=(",", ":")) + json.dumps(_BODY, separators=(",", ":"))


def _make_sftp(raw_bytes: bytes = _RAW.encode()) -> MagicMock:
    sftp = MagicMock(spec=SFTPService)
    sftp.download_bytes = AsyncMock(return_value=raw_bytes)
    return sftp


def _make_session() -> MagicMock:
    """Build a session mock with sync `add` and async `execute`/`flush`."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


async def _noop_event(level: str, msg: str, ctx: object = None) -> None:
    pass


def _exec_result(scalar: object = None, scalars_all: list | None = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalars.return_value.all.return_value = scalars_all if scalars_all is not None else []
    r.all.return_value = scalars_all if scalars_all is not None else []
    return r


# ---------------------------------------------------------------------------
# dry_run behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_returns_early() -> None:
    """dry_run=True downloads but skips parse and DB writes."""
    session = _make_session()
    sftp = _make_sftp()

    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=True,
        on_event=_noop_event,
    )
    result = await orc.run()

    assert result.dry_run is True
    assert result.feeds_created == 0
    assert result.subscriptions_created == 0
    sftp.download_bytes.assert_awaited_once_with("/remote/yarss2.conf", dry_run=True)
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Happy-path: feeds upsert (tested via _upsert_feeds directly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_feeds_creates_new_feed() -> None:
    """A feed not in the DB is created."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    session.execute = AsyncMock(return_value=_exec_result(scalar=None))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    rssfeeds = {"0": {"name": "ShowRSS", "url": "https://showrss.info/feed"}}
    result = RssImportResult()
    await orc._upsert_feeds(rssfeeds, result)

    assert result.feeds_created == 1
    assert result.feeds_updated == 0
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_feeds_updates_existing_feed() -> None:
    """A feed already in the DB is updated, not duplicated."""
    from jidou.models.rss import RssFeed
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    existing_feed = MagicMock(spec=RssFeed)
    existing_feed.id = 1
    session.execute = AsyncMock(return_value=_exec_result(scalar=existing_feed))

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    rssfeeds = {"0": {"name": "ShowRSS", "url": "https://showrss.info/feed"}}
    result = RssImportResult()
    key_to_id = await orc._upsert_feeds(rssfeeds, result)

    assert result.feeds_updated == 1
    assert result.feeds_created == 0
    assert key_to_id["0"] == 1
    assert existing_feed.name == "ShowRSS"
    assert existing_feed.url == "https://showrss.info/feed"


# ---------------------------------------------------------------------------
# Happy-path: subscriptions upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriptions_created_for_new_keys() -> None:
    """Remote subscriptions not in DB are added as new rows."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()
    # First execute: db_subs (empty), second: shows (empty)
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[]), _exec_result(scalars_all=[])]
    )

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {
        "0": {"name": "The Last of Us", "active": True},
        "1": {"name": "Severance", "active": True},
    }
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.subscriptions_created == 2
    assert result.subscriptions_updated == 0
    assert session.add.call_count == 2


@pytest.mark.asyncio
async def test_show_auto_linked_by_name() -> None:
    """A subscription whose name matches a show title gets show_id set."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    session = _make_session()

    show_row = MagicMock()
    show_row.id = 42
    show_row.title = "The Last of Us"
    shows_result = MagicMock()
    shows_result.all.return_value = [show_row]

    session.execute = AsyncMock(side_effect=[_exec_result(scalars_all=[]), shows_result])

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )

    remote_subs = {"0": {"name": "The Last of Us", "active": True}}
    result = RssImportResult()
    await orc._upsert_subscriptions(remote_subs, {}, result)

    assert result.shows_linked == 1
    added_sub = session.add.call_args_list[0].args[0]
    assert isinstance(added_sub, RssSubscription)
    assert added_sub.show_id == 42


@pytest.mark.asyncio
async def test_remote_deleted_keys_logged() -> None:
    """Keys in DB but absent from remote are reported as remote-deleted."""
    from jidou.models.rss import RssSubscription
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    db_sub = MagicMock(spec=RssSubscription)
    db_sub.remote_key = "99"

    session = _make_session()
    session.execute = AsyncMock(
        side_effect=[_exec_result(scalars_all=[db_sub]), _exec_result(scalars_all=[])]
    )

    events: list[str] = []

    async def capture_event(level: str, msg: str, ctx: object = None) -> None:
        events.append(f"{level}:{msg}")

    sftp = _make_sftp()
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=capture_event,
    )

    result = RssImportResult()
    await orc._upsert_subscriptions({}, {}, result)

    assert result.subscriptions_remote_deleted == 1
    assert any("99" in e for e in events)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_error_returns_result_with_error_message() -> None:
    """If the raw content is not parseable, returns result with errors list."""
    session = _make_session()
    sftp = _make_sftp(b"this is not valid json at all")
    orc = RssImportOrchestrator(
        session=session,
        sftp=sftp,
        remote_path="/remote/yarss2.conf",
        dry_run=False,
        on_event=_noop_event,
    )
    result = await orc.run()

    assert len(result.errors) == 1
    assert "parse" in result.errors[0].lower()
    assert result.snapshot_id is None
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/rss/import endpoint
# ---------------------------------------------------------------------------


def test_import_endpoint_422_when_path_not_configured() -> None:
    """POST /api/rss/import returns 422 when RSS_CONFIG_REMOTE_PATH is not set."""
    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app

    async def _mock_session() -> MagicMock:
        session = _make_session()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        with patch("jidou.api.routes.rss.settings") as mock_settings:
            mock_settings.rss_config_remote_path = None
            r = TestClient(app).post("/api/rss/import")
        assert r.status_code == 422
        assert "RSS_CONFIG_REMOTE_PATH" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_import_endpoint_202_when_path_configured() -> None:
    """POST /api/rss/import returns 202 and a task record when configured."""
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app
    from jidou.models.task import BackgroundTask

    task = MagicMock(spec=BackgroundTask)
    task.id = 1
    task.celery_task_id = "abc-123"
    task.task_type = "rss_import"
    task.status = "pending"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_message = None
    task.result_summary = None
    task.dry_run = False
    now = datetime.now(UTC)
    task.created_at = now
    task.updated_at = now
    task.completed_at = None
    task.event_log = []

    async def _mock_session() -> MagicMock:
        session = _make_session()
        yield session

    app.dependency_overrides[get_session] = _mock_session
    try:
        with (
            patch("jidou.api.routes.rss.settings") as mock_settings,
            patch("jidou.api.routes.rss.create_task_record", new=AsyncMock(return_value=task)),
            patch("jidou.workers.rss_tasks.rss_import_task") as mock_task,
        ):
            mock_settings.rss_config_remote_path = "/remote/yarss2.conf"
            mock_task.apply_async = MagicMock()
            r = TestClient(app).post("/api/rss/import")
        assert r.status_code == 202
        mock_task.apply_async.assert_called_once()
    finally:
        app.dependency_overrides.clear()

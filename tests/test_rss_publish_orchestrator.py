"""Tests for RssPublishOrchestrator and the rss_publish_task / publish endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_RAW = '{"file":1,"format":1}{"subscriptions":{"0":{"name":"TestSub"}},"rssfeeds":{"f1":{"name":"Feed1","url":"http://f1.example/rss"}},"cookies":{},"general":{}}'


def _make_session() -> MagicMock:
    """Return a MagicMock session with async methods wired correctly."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


def _exec_result(
    scalar: object = None,
    scalars_all: list[object] | None = None,
) -> MagicMock:
    """Build a mock execute() return value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_all or []
    r.scalars.return_value = scalars_mock
    r.all.return_value = scalars_all or []
    return r


def _make_feed(
    *,
    id: int = 1,
    remote_key: str | None = "f1",
    name: str = "Feed1",
    url: str = "http://f1.example/rss",
    default_download_location: str | None = "/downloads",
    default_move_completed: str | None = None,
    extra_config: dict | None = None,
) -> MagicMock:
    feed = MagicMock()
    feed.id = id
    feed.remote_key = remote_key
    feed.name = name
    feed.url = url
    feed.default_download_location = default_download_location
    feed.default_move_completed = default_move_completed
    feed.extra_config = extra_config
    return feed


def _make_sub(
    *,
    id: int = 1,
    remote_key: str | None = "0",
    name: str = "TestSub",
    enabled_in_config: bool = True,
    feed: MagicMock | None = None,
    regex_include: str | None = None,
    regex_exclude: str | None = None,
    regex_include_ignorecase: bool = True,
    regex_exclude_ignorecase: bool = True,
    download_location: str | None = None,
    move_completed: str | None = None,
    active: bool = True,
    label: str | None = None,
    last_match: str | None = None,
    extra_config: dict | None = None,
) -> MagicMock:
    sub = MagicMock()
    sub.id = id
    sub.remote_key = remote_key
    sub.name = name
    sub.enabled_in_config = enabled_in_config
    sub.feed = feed
    sub.regex_include = regex_include
    sub.regex_exclude = regex_exclude
    sub.regex_include_ignorecase = regex_include_ignorecase
    sub.regex_exclude_ignorecase = regex_exclude_ignorecase
    sub.download_location = download_location
    sub.move_completed = move_completed
    sub.active = active
    sub.label = label
    sub.last_match = last_match
    sub.extra_config = extra_config
    return sub


def _import_result_ok(raw_content: str = _MINIMAL_RAW, snapshot_id: int = 99) -> MagicMock:
    """Return an RssImportResult mock with no errors."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult

    r = RssImportResult()
    r.raw_content = raw_content
    r.snapshot_id = snapshot_id
    r.errors = []
    return r


def _std_execute_sides(
    feeds: list[object],
    db_keys: list[str],
    subs: list[object],
) -> list[MagicMock]:
    """Return the three execute side-effects in order:
    1. feeds query (_build_feeds_dict)
    2. all-DB-keys query (collision-avoidance in run())
    3. enabled-subs query (_build_subscriptions_dict)
    """
    return [
        _exec_result(scalars_all=feeds),
        _exec_result(scalars_all=db_keys),
        _exec_result(scalars_all=subs),
    ]


# ---------------------------------------------------------------------------
# RssPublishOrchestrator unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_dry_run_does_not_upload() -> None:
    """dry_run=True: upload_bytes is never called."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    feed = _make_feed()
    sub = _make_sub(feed=feed)
    session.execute = AsyncMock(side_effect=_std_execute_sides([feed], ["0"], [sub]))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=True)
        result = await orc.run()

    sftp.upload_bytes.assert_not_called()
    assert result.dry_run is True
    assert not result.errors


@pytest.mark.asyncio
async def test_publish_uploads_backup_and_config() -> None:
    """Live run: upload_bytes called twice — backup first, then new config."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    feed = _make_feed()
    sub = _make_sub(feed=feed)
    session.execute = AsyncMock(side_effect=_std_execute_sides([feed], ["0"], [sub]))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        result = await orc.run()

    assert sftp.upload_bytes.call_count == 2
    backup_call_path = sftp.upload_bytes.call_args_list[0][0][1]
    assert "backup" in backup_call_path
    assert result.backup_path is not None
    assert "backup" in result.backup_path
    config_call_path = sftp.upload_bytes.call_args_list[1][0][1]
    assert config_call_path == "/remote/yarss2.conf"
    assert not result.errors


@pytest.mark.asyncio
async def test_publish_builds_feeds_from_db() -> None:
    """Published feeds dict reflects DB RssFeed rows with a remote_key."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()

    feed = _make_feed(remote_key="f1", name="My Feed", url="http://x.example/rss")
    sub = _make_sub(feed=feed)
    session.execute = AsyncMock(side_effect=_std_execute_sides([feed], ["0"], [sub]))

    uploaded_configs: list[bytes] = []

    async def capture_upload(data: bytes, path: str) -> None:
        uploaded_configs.append(data)

    sftp.upload_bytes = AsyncMock(side_effect=capture_upload)

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        result = await orc.run()

    import json

    _, new_config_raw = uploaded_configs
    new_config_str = new_config_raw.decode("utf-8")
    decoder = json.JSONDecoder()
    _hdr, offset = decoder.raw_decode(new_config_str)
    body, _ = decoder.raw_decode(new_config_str, offset)
    assert "f1" in body["rssfeeds"]
    assert body["rssfeeds"]["f1"]["name"] == "My Feed"
    assert result.feeds_published == 1


@pytest.mark.asyncio
async def test_publish_assigns_keys_to_stubs() -> None:
    """New stubs (remote_key=None) get sequential keys starting at max_key + 1."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    feed = _make_feed()
    stub = _make_sub(remote_key=None, name="New Show", feed=feed)
    # DB remote keys: ["0"] — matches the remote body max key of 0
    session.execute = AsyncMock(side_effect=_std_execute_sides([feed], ["0"], [stub]))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        result = await orc.run()

    # Remote body has key "0"; stub gets key "1"
    assert stub.remote_key == "1"
    assert result.new_keys_assigned == 1
    assert result.subscriptions_published == 1
    session.flush.assert_called()


@pytest.mark.asyncio
async def test_publish_avoids_collision_with_remote_deleted_db_keys() -> None:
    """Stub keys skip over remote_keys held by DB subs that no longer exist remotely."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    # Remote body max key is "0"; but DB has another sub with remote_key="1"
    # (e.g., it was remote-deleted). A new stub must get key "2", not "1".
    raw = (
        '{"file":1,"format":1}'
        '{"subscriptions":{"0":{"name":"Existing"}},"rssfeeds":{},"cookies":{}}'
    )
    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    stub = _make_sub(remote_key=None, name="New Show", feed=None)
    # All DB remote_keys include "0" AND "1" (the remote-deleted one)
    session.execute = AsyncMock(side_effect=_std_execute_sides([], ["0", "1"], [stub]))

    import_result = _import_result_ok(raw_content=raw, snapshot_id=5)

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=import_result)
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        result = await orc.run()

    assert stub.remote_key == "2"
    assert result.new_keys_assigned == 1


@pytest.mark.asyncio
async def test_publish_dry_run_does_not_assign_keys() -> None:
    """Stubs are not mutated in dry_run mode."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    stub = _make_sub(remote_key=None, name="Stub Show", feed=_make_feed())
    session.execute = AsyncMock(side_effect=_std_execute_sides([_make_feed()], [], [stub]))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=True)
        result = await orc.run()

    assert stub.remote_key is None
    assert result.new_keys_assigned == 1  # counted but not persisted
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_publish_falls_back_to_feed_download_location() -> None:
    """When sub.download_location is None, feed.default_download_location is used."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()

    uploaded_configs: list[bytes] = []

    async def capture_upload(data: bytes, path: str) -> None:
        uploaded_configs.append(data)

    sftp.upload_bytes = AsyncMock(side_effect=capture_upload)

    feed = _make_feed(default_download_location="/media/downloads")
    sub = _make_sub(feed=feed, download_location=None)
    session.execute = AsyncMock(side_effect=_std_execute_sides([feed], ["0"], [sub]))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        await orc.run()

    import json

    _, new_config_raw = uploaded_configs
    decoder = json.JSONDecoder()
    _hdr, offset = decoder.raw_decode(new_config_raw.decode())
    body, _ = decoder.raw_decode(new_config_raw.decode(), offset)
    sub_entry = body["subscriptions"]["0"]
    assert sub_entry["download_location"] == "/media/downloads"


@pytest.mark.asyncio
async def test_publish_preserves_passthrough_sections() -> None:
    """Non-managed sections (cookies, general, etc.) from old_body are preserved."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    raw = (
        '{"file":1,"format":1}'
        '{"subscriptions":{},"rssfeeds":{},'
        '"cookies":{"token":"abc"},"general":{"foo":"bar"},"email_messages":{}}'
    )
    session = _make_session()
    sftp = MagicMock()
    uploaded_configs: list[bytes] = []

    async def capture(data: bytes, path: str) -> None:
        uploaded_configs.append(data)

    sftp.upload_bytes = AsyncMock(side_effect=capture)

    session.execute = AsyncMock(side_effect=_std_execute_sides([], [], []))

    import_result = _import_result_ok(raw_content=raw, snapshot_id=10)

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=import_result)
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf", dry_run=False)
        await orc.run()

    import json

    _, new_config_raw = uploaded_configs
    decoder = json.JSONDecoder()
    _hdr, offset = decoder.raw_decode(new_config_raw.decode())
    body, _ = decoder.raw_decode(new_config_raw.decode(), offset)
    assert body["cookies"] == {"token": "abc"}
    assert body["general"] == {"foo": "bar"}
    assert "email_messages" in body


@pytest.mark.asyncio
async def test_publish_returns_errors_when_import_fails() -> None:
    """When import reconciliation returns errors, publish aborts and surfaces them."""
    from jidou.orchestrators.rss_import_orchestrator import RssImportResult
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    bad_result = RssImportResult(errors=["parse error: unexpected EOF"])

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=bad_result)
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf")
        result = await orc.run()

    assert "parse error" in result.errors[0]
    sftp.upload_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_publish_snapshot_type_passed_to_import_orc() -> None:
    """RssImportOrchestrator is constructed with snapshot_type='pre_publish'."""
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishOrchestrator

    session = _make_session()
    sftp = MagicMock()
    sftp.upload_bytes = AsyncMock()

    session.execute = AsyncMock(side_effect=_std_execute_sides([], [], []))

    with patch(
        "jidou.orchestrators.rss_publish_orchestrator.RssImportOrchestrator"
    ) as mock_orc_cls:
        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=_import_result_ok())
        mock_orc_cls.return_value = mock_orc

        orc = RssPublishOrchestrator(session, sftp, "/remote/yarss2.conf")
        await orc.run()

    _, kwargs = mock_orc_cls.call_args
    assert kwargs.get("snapshot_type") == "pre_publish"


# ---------------------------------------------------------------------------
# Celery task test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_celery_publish_task_marks_failed_and_raises() -> None:
    """_rss_publish marks the task FAILED and raises when orchestrator returns errors."""
    from jidou.models.task import TaskStatus
    from jidou.orchestrators.rss_publish_orchestrator import RssPublishResult
    from jidou.workers.rss_tasks import _rss_publish

    error_result = RssPublishResult(errors=["Backup upload failed"])

    captured_statuses: list[TaskStatus] = []

    async def fake_update_status(
        session: object, task_id: str, status: TaskStatus, **kw: object
    ) -> None:
        captured_statuses.append(status)

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    task_mock = MagicMock()
    task_mock.status = TaskStatus.PENDING.value

    with (
        patch("jidou.workers.rss_tasks.create_async_engine", return_value=mock_engine),
        patch("jidou.workers.rss_tasks.async_sessionmaker") as mock_factory,
        patch("jidou.workers.rss_tasks.create_task_record", new=AsyncMock(return_value=task_mock)),
        patch("jidou.workers.rss_tasks.update_task_status", side_effect=fake_update_status),
        patch("jidou.workers.rss_tasks.RssPublishOrchestrator") as mock_orc_cls,
        patch("jidou.workers.rss_tasks._build_sftp", return_value=MagicMock()),
        patch("jidou.workers.rss_tasks.emit_progress", new=AsyncMock()),
    ):
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value.return_value = session_cm

        mock_orc = MagicMock()
        mock_orc.run = AsyncMock(return_value=error_result)
        mock_orc_cls.return_value = mock_orc

        with pytest.raises(RuntimeError, match="Publish failed"):
            await _rss_publish("test-publish-task-id", dry_run=False)

    assert TaskStatus.RUNNING in captured_statuses
    assert TaskStatus.FAILED in captured_statuses
    assert TaskStatus.COMPLETED not in captured_statuses


# ---------------------------------------------------------------------------
# POST /api/rss/publish endpoint tests
# ---------------------------------------------------------------------------


def test_publish_endpoint_422_when_path_not_configured() -> None:
    """POST /api/rss/publish returns 422 when RSS_CONFIG_REMOTE_PATH is not set."""
    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app

    async def _mock_session() -> MagicMock:
        session = _make_session()
        yield session

    app.dependency_overrides[get_session] = _mock_session

    with (
        patch("jidou.api.routes.rss.settings") as mock_settings,
        TestClient(app) as client,
    ):
        mock_settings.rss_config_remote_path = None
        resp = client.post("/api/rss/publish")

    app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_publish_endpoint_202_when_path_configured() -> None:
    """POST /api/rss/publish returns 202 and dispatches the Celery task."""
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from jidou.database import get_session
    from jidou.main import app
    from jidou.models.task import BackgroundTask

    task = MagicMock(spec=BackgroundTask)
    task.id = 1
    task.celery_task_id = "pub-task-id"
    task.task_type = "rss_publish"
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

    with (
        patch("jidou.api.routes.rss.settings") as mock_settings,
        patch("jidou.api.routes.rss.create_task_record", new=AsyncMock(return_value=task)),
        patch("jidou.workers.rss_tasks.rss_publish_task") as mock_task,
        TestClient(app) as client,
    ):
        mock_settings.rss_config_remote_path = "/remote/yarss2.conf"
        mock_task.apply_async = MagicMock()
        resp = client.post("/api/rss/publish")

    app.dependency_overrides.clear()
    assert resp.status_code == 202

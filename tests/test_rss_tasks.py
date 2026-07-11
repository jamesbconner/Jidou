"""Tests for rss_tasks — RSS import and publish Celery workers."""

from unittest.mock import AsyncMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.orchestrators.rss_import_orchestrator import RssImportResult
from jidou.orchestrators.rss_publish_orchestrator import RssPublishResult


def _capture_run_task_workflow(module_path: str) -> tuple:
    """Patch <module_path>.run_task_workflow, capturing its call kwargs and `work` callback.

    Mirrors the helper in tests/test_workers.py -- lifecycle machinery
    (redelivery skip, RUNNING/COMPLETED/CANCELLED/FAILED transitions,
    on_progress/on_event plumbing, soft-failure handling) is covered once,
    generically, in tests/test_worker_harness.py. These tests only need to
    verify rss_tasks' own orchestrator wiring and WorkflowResult shape.
    """
    captured: dict[str, object] = {}

    async def fake_run_task_workflow(
        celery_task_id: str,
        task_type: str,
        work: object,
        *,
        progress_total: int = 0,
        dry_run: bool = False,
        running_message: str = "",
    ) -> str:
        captured["celery_task_id"] = celery_task_id
        captured["task_type"] = task_type
        captured["work"] = work
        captured["progress_total"] = progress_total
        captured["dry_run"] = dry_run
        captured["running_message"] = running_message
        return celery_task_id

    return patch(f"{module_path}.run_task_workflow", side_effect=fake_run_task_workflow), captured


# ---------------------------------------------------------------------------
# rss_import_task (sync wrapper) — soft timeout
# ---------------------------------------------------------------------------


def test_rss_import_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in rss_import_task must call mark_task_timed_out."""
    from jidou.workers.rss_tasks import rss_import_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.rss_tasks._rss_import",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.rss_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        rss_import_task(dry_run=False)

    assert len(mark_calls) == 1


# ---------------------------------------------------------------------------
# _rss_import — orchestrator wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_import_wires_orchestrator_and_returns_summary() -> None:
    """_rss_import wires run_task_workflow, and its `work` closure calls RssImportOrchestrator."""
    from jidou.workers.rss_tasks import _rss_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        result = await _rss_import("tid-ri1", dry_run=True)

    assert result == "tid-ri1"
    assert captured["task_type"] == "rss_import"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True
    assert captured["running_message"] == "Downloading RSS config…"

    import_result = RssImportResult(
        feeds_created=2,
        feeds_updated=0,
        subscriptions_created=5,
        subscriptions_updated=1,
        subscriptions_remote_deleted=0,
        shows_linked=3,
        snapshot_id=42,
        errors=[],
        dry_run=True,
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.rss_tasks._build_sftp") as mock_build_sftp,
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=import_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_build_sftp.assert_called_once()
    mock_run.assert_awaited_once()
    assert not wf_result.errors
    assert wf_result.result_summary == {
        "feeds_created": 2,
        "feeds_updated": 0,
        "subscriptions_created": 5,
        "subscriptions_updated": 1,
        "subscriptions_remote_deleted": 0,
        "shows_linked": 3,
        "snapshot_id": 42,
        "errors": [],
        "dry_run": True,
    }


@pytest.mark.asyncio
async def test_rss_import_error_result_becomes_soft_failure() -> None:
    """RssImportOrchestrator errors become a soft failure on the WorkflowResult."""
    from jidou.workers.rss_tasks import _rss_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        await _rss_import("tid-ri2", dry_run=False)

    error_result = RssImportResult(errors=["config not found"])
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=error_result,
        ),
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert wf_result.errors == ["config not found"]
    assert wf_result.message == "Import failed: config not found"
    assert wf_result.result_summary == {"errors": ["config not found"], "dry_run": False}


@pytest.mark.asyncio
async def test_rss_import_wires_on_event_to_orchestrator() -> None:
    """RssImportOrchestrator receives the harness's on_event at construction time."""
    from jidou.workers.rss_tasks import RssImportOrchestrator, _rss_import

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        await _rss_import("tid-ri3", dry_run=False)

    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    captured_kwargs: dict[str, object] = {}
    real_init = RssImportOrchestrator.__init__

    def fake_init(self: object, **kwargs: object) -> None:
        captured_kwargs.update(kwargs)
        real_init(self, **kwargs)  # type: ignore[arg-type]

    with (
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch.object(RssImportOrchestrator, "__init__", fake_init),
        patch(
            "jidou.workers.rss_tasks.RssImportOrchestrator.run",
            new_callable=AsyncMock,
            return_value=RssImportResult(errors=[]),
        ),
    ):
        await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert captured_kwargs["on_event"] is on_event


# ---------------------------------------------------------------------------
# rss_publish_task (sync wrapper) — soft timeout
# ---------------------------------------------------------------------------


def test_rss_publish_task_soft_timeout_calls_mark_timed_out() -> None:
    """SoftTimeLimitExceeded in rss_publish_task must call mark_task_timed_out."""
    from jidou.workers.rss_tasks import rss_publish_task

    mark_calls: list[str] = []

    async def fake_mark(celery_task_id: str) -> None:
        mark_calls.append(celery_task_id)

    with (
        patch(
            "jidou.workers.rss_tasks._rss_publish",
            new_callable=AsyncMock,
            side_effect=SoftTimeLimitExceeded(),
        ),
        patch("jidou.workers.rss_tasks.mark_task_timed_out", side_effect=fake_mark),
        pytest.raises(SoftTimeLimitExceeded),
    ):
        rss_publish_task(dry_run=False)

    assert len(mark_calls) == 1


# ---------------------------------------------------------------------------
# _rss_publish — orchestrator wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_publish_wires_orchestrator_and_returns_summary() -> None:
    """_rss_publish wires run_task_workflow, and its `work` closure calls RssPublishOrchestrator."""
    from jidou.workers.rss_tasks import _rss_publish

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        result = await _rss_publish("tid-rp1", dry_run=True)

    assert result == "tid-rp1"
    assert captured["task_type"] == "rss_publish"
    assert captured["progress_total"] == 0
    assert captured["dry_run"] is True
    assert captured["running_message"] == "Publishing RSS config…"

    publish_result = RssPublishResult(
        feeds_published=3,
        subscriptions_published=10,
        new_keys_assigned=2,
        snapshot_id=7,
        backup_path="/tmp/backup.xml",
        errors=[],
    )
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.rss_tasks._build_sftp") as mock_build_sftp,
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=publish_result,
        ) as mock_run,
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    mock_build_sftp.assert_called_once()
    mock_run.assert_awaited_once()
    assert not wf_result.errors
    assert wf_result.result_summary == {
        "feeds_published": 3,
        "subscriptions_published": 10,
        "new_keys_assigned": 2,
        "snapshot_id": 7,
        "backup_path": "/tmp/backup.xml",
        "dry_run": True,
    }


@pytest.mark.asyncio
async def test_rss_publish_error_result_becomes_soft_failure() -> None:
    """RssPublishOrchestrator errors become a soft failure on the WorkflowResult."""
    from jidou.workers.rss_tasks import _rss_publish

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        await _rss_publish("tid-rp2", dry_run=False)

    error_result = RssPublishResult(errors=["upload failed"])
    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    with (
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=error_result,
        ),
    ):
        wf_result = await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert wf_result.errors == ["upload failed"]
    assert wf_result.message == "Publish failed: upload failed"
    assert wf_result.result_summary == {"errors": ["upload failed"], "dry_run": False}


@pytest.mark.asyncio
async def test_rss_publish_wires_on_event_to_orchestrator() -> None:
    """RssPublishOrchestrator receives the harness's on_event at construction time."""
    from jidou.workers.rss_tasks import RssPublishOrchestrator, _rss_publish

    patcher, captured = _capture_run_task_workflow("jidou.workers.rss_tasks")
    with patcher:
        await _rss_publish("tid-rp3", dry_run=False)

    session = AsyncMock()
    on_progress = AsyncMock()
    on_event = AsyncMock()
    captured_kwargs: dict[str, object] = {}
    real_init = RssPublishOrchestrator.__init__

    def fake_init(self: object, **kwargs: object) -> None:
        captured_kwargs.update(kwargs)
        real_init(self, **kwargs)  # type: ignore[arg-type]

    with (
        patch("jidou.workers.rss_tasks._build_sftp"),
        patch.object(RssPublishOrchestrator, "__init__", fake_init),
        patch(
            "jidou.workers.rss_tasks.RssPublishOrchestrator.run",
            new_callable=AsyncMock,
            return_value=RssPublishResult(errors=[]),
        ),
    ):
        await captured["work"](session, on_progress, on_event)  # type: ignore[operator]

    assert captured_kwargs["on_event"] is on_event

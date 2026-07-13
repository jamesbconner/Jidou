"""Tests for the /tasks REST API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.main import app
from jidou.models.task import BackgroundTask, TaskStatus


def _make_task(
    *,
    id: int = 1,
    celery_task_id: str = "celery-abc",
    task_type: str = "scan",
    status: str = TaskStatus.PENDING.value,
) -> MagicMock:
    """Build a minimal BackgroundTask mock suitable for route responses."""
    from datetime import UTC, datetime

    task = MagicMock(spec=BackgroundTask)
    task.id = id
    task.celery_task_id = celery_task_id
    task.task_type = task_type
    task.status = status
    task.progress_current = 0
    task.progress_total = 0
    task.progress_message = None
    task.result_summary = None
    task.dry_run = False
    task.created_at = datetime.now(UTC)
    task.completed_at = None
    return task


# ---------------------------------------------------------------------------
# POST /api/tasks/trigger
# ---------------------------------------------------------------------------


def test_trigger_task_unknown_type_returns_400() -> None:
    """An unrecognised task_type must return 400 without dispatching."""
    client = TestClient(app)
    response = client.post("/api/tasks/trigger", json={"task_type": "explode"})
    assert response.status_code == 400
    assert "Unknown task type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_task_download_no_show_id_accepted() -> None:
    """download is a global operation — schema must accept it without show_id."""
    from unittest.mock import patch

    from jidou.database import get_session

    mock_task = _make_task(celery_task_id="dl-no-show-id")

    async def _mock_session():  # type: ignore[no-untyped-def]
        session = AsyncMock()
        yield session

    mock_celery = MagicMock()
    mock_celery.apply_async.return_value = MagicMock(id="dl-no-show-id")

    app.dependency_overrides[get_session] = _mock_session
    try:
        with (
            patch(
                "jidou.services.progress.create_task_record",
                new_callable=AsyncMock,
                return_value=mock_task,
            ),
            patch(
                "jidou.workers.download_tasks.download_files_task",
                mock_celery,
            ),
        ):
            response = TestClient(app).post("/api/tasks/trigger", json={"task_type": "download"})
        # Must NOT be 422 (schema validation) — download no longer requires show_id
        assert response.status_code != 422
        mock_celery.apply_async.assert_called_once()
        # Confirm show_id is absent from the dispatch args
        call_args = mock_celery.apply_async.call_args
        assert call_args is not None
        dispatched_args = call_args[1].get("args") or call_args[0][0]
        assert len(dispatched_args) == 1  # only dry_run
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_task_creates_row_before_dispatch() -> None:
    """The DB row must be created BEFORE the Celery task is dispatched."""
    creation_order: list[str] = []

    mock_task = _make_task(celery_task_id="pre-gen-id")

    async def mock_create_task_record(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        creation_order.append("db_row")
        return mock_task

    def mock_apply_async(*args, **kwargs):  # type: ignore[no-untyped-def]
        creation_order.append("celery_dispatch")
        return MagicMock(id="pre-gen-id")

    mock_celery_task = MagicMock()
    mock_celery_task.apply_async.side_effect = mock_apply_async

    # Deferred imports inside trigger_task must be patched at their source modules.
    with (
        patch("jidou.services.progress.create_task_record", side_effect=mock_create_task_record),
        patch("jidou.workers.scan_tasks.scan_remote_task", mock_celery_task),
    ):
        client = TestClient(app)
        client.post("/api/tasks/trigger", json={"task_type": "scan", "dry_run": False})

    assert creation_order == ["db_row", "celery_dispatch"], (
        "DB row must be created before Celery dispatch"
    )


# ---------------------------------------------------------------------------
# POST /api/tasks/trigger — route overlap guard
#
# RouteOrchestrator selects all MATCHED/ROUTING files upfront and commits each
# file's status transition individually inside the loop, rather than claiming
# rows atomically. Two overlapping route dispatches (e.g. RematchModal firing
# one per fix) can each see the same still-MATCHED file in their own initial
# SELECT and both route it, producing duplicate copies at the destination.
# See https://github.com/jamesbconner/Jidou/issues/357.
# ---------------------------------------------------------------------------


def test_trigger_task_route_reuses_active_task_instead_of_duplicating() -> None:
    """route must not dispatch a second time while one is already active."""
    active_task = _make_task(
        id=99, celery_task_id="already-running", task_type="route", status=TaskStatus.RUNNING.value
    )
    mock_celery = MagicMock()

    with (
        patch(
            "jidou.services.progress.get_active_task",
            new_callable=AsyncMock,
            return_value=active_task,
        ),
        patch("jidou.workers.route_tasks.route_files_task", mock_celery),
    ):
        response = TestClient(app).post("/api/tasks/trigger", json={"task_type": "route"})

    assert response.status_code == 200
    assert response.json()["celery_task_id"] == "already-running"
    mock_celery.apply_async.assert_not_called()


def test_trigger_task_route_dispatches_when_no_active_task() -> None:
    """route dispatches normally when no route task is currently active."""
    mock_task = _make_task(celery_task_id="new-route-run", task_type="route")
    mock_celery = MagicMock()
    mock_celery.apply_async.return_value = MagicMock(id="new-route-run")

    with (
        patch(
            "jidou.services.progress.get_active_task",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "jidou.services.progress.create_task_record",
            new_callable=AsyncMock,
            return_value=mock_task,
        ),
        patch("jidou.workers.route_tasks.route_files_task", mock_celery),
    ):
        response = TestClient(app).post("/api/tasks/trigger", json={"task_type": "route"})

    assert response.status_code == 200
    mock_celery.apply_async.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/tasks/{task_id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_task_not_found_returns_404() -> None:
    """Cancelling a non-existent task must return 404."""
    with patch("jidou.database.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=lambda s: MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        mock_factory.return_value.__aenter__.return_value = mock_session
        mock_factory.return_value.__aexit__.return_value = False

        client = TestClient(app)
        response = client.post("/api/tasks/999/cancel")
    assert response.status_code == 404


def test_cancel_already_completed_returns_400() -> None:
    """Cancelling a COMPLETED task must return 400."""
    completed_task = _make_task(status=TaskStatus.COMPLETED.value)

    with patch("jidou.database.async_session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = completed_task
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_factory.return_value.__aenter__.return_value = mock_session
        mock_factory.return_value.__aexit__.return_value = False

        client = TestClient(app)
        response = client.post("/api/tasks/1/cancel")
    assert response.status_code == 400
    assert "not running" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/tasks
# ---------------------------------------------------------------------------


def _session_override(task_or_list: "BackgroundTask | list[BackgroundTask] | None"):  # type: ignore[return]
    """Return a FastAPI dependency override that yields a mock session."""

    async def _mock_session() -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        if isinstance(task_or_list, list):
            result.scalars.return_value.all.return_value = task_or_list
        else:
            result.scalar_one_or_none.return_value = task_or_list
            result.scalars.return_value.all.return_value = [task_or_list] if task_or_list else []
        session.execute = AsyncMock(return_value=result)
        yield session

    return _mock_session


def test_list_tasks_returns_200() -> None:
    """GET /api/tasks must return a 200 with a list payload."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override([])
    try:
        client = TestClient(app)
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    finally:
        app.dependency_overrides.clear()


def test_get_task_not_found_returns_404() -> None:
    """GET /api/tasks/{task_id} must return 404 for missing tasks."""
    from jidou.database import get_session

    app.dependency_overrides[get_session] = _session_override(None)
    try:
        client = TestClient(app)
        response = client.get("/api/tasks/999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_get_task_found_returns_200() -> None:
    """GET /api/tasks/{task_id} must return the task for an existing ID."""
    from jidou.database import get_session

    task = _make_task(id=5, celery_task_id="abc-123", status=TaskStatus.RUNNING.value)
    app.dependency_overrides[get_session] = _session_override(task)
    try:
        client = TestClient(app)
        response = client.get("/api/tasks/5")
        assert response.status_code == 200
        data = response.json()
        assert data["celery_task_id"] == "abc-123"
    finally:
        app.dependency_overrides.clear()


def test_cancel_running_task_succeeds() -> None:
    """POST /api/tasks/{task_id}/cancel must set status to CANCELLED."""
    from jidou.database import get_session

    task = _make_task(id=7, celery_task_id="run-123", status=TaskStatus.RUNNING.value)
    app.dependency_overrides[get_session] = _session_override(task)
    try:
        with (
            patch("jidou.api.routes.tasks.celery_app"),
            patch("jidou.services.progress.emit_progress", new_callable=AsyncMock),
        ):
            client = TestClient(app)
            response = client.post("/api/tasks/7/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.CANCELLED.value
    finally:
        app.dependency_overrides.clear()


def test_trigger_task_sync_dispatches() -> None:
    """POST /api/tasks/trigger with task_type=sync must dispatch sync_all_task."""
    mock_task = _make_task(celery_task_id="sync-id")
    dispatched: list[str] = []

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        dispatched.append("create")
        return mock_task

    mock_sync = MagicMock()
    mock_sync.apply_async.side_effect = lambda *a, **kw: dispatched.append("dispatch")

    with (
        patch("jidou.services.progress.create_task_record", side_effect=fake_create),
        patch("jidou.workers.sync_tasks.sync_all_task", mock_sync),
    ):
        client = TestClient(app)
        client.post("/api/tasks/trigger", json={"task_type": "sync"})

    assert dispatched == ["create", "dispatch"]


@pytest.mark.asyncio
async def test_trigger_task_match_no_show_id_accepted() -> None:
    """match is a global operation — schema must accept it without show_id."""
    from unittest.mock import patch

    from jidou.database import get_session

    mock_task = _make_task(celery_task_id="match-no-show-id")

    async def _mock_session():  # type: ignore[no-untyped-def]
        session = AsyncMock()
        yield session

    mock_celery = MagicMock()
    mock_celery.apply_async.return_value = MagicMock(id="match-no-show-id")

    app.dependency_overrides[get_session] = _mock_session
    try:
        with (
            patch(
                "jidou.services.progress.create_task_record",
                new_callable=AsyncMock,
                return_value=mock_task,
            ),
            patch(
                "jidou.workers.match_tasks.match_files_task",
                mock_celery,
            ),
        ):
            response = TestClient(app).post("/api/tasks/trigger", json={"task_type": "match"})
        assert response.status_code != 422
        mock_celery.apply_async.assert_called_once()
        call_args = mock_celery.apply_async.call_args
        assert call_args is not None
        dispatched_args = call_args[1].get("args") or call_args[0][0]
        assert len(dispatched_args) == 1  # only dry_run
    finally:
        app.dependency_overrides.clear()


def test_trigger_task_broker_failure_marks_task_failed() -> None:
    """A broker dispatch failure must mark the row FAILED and return 503."""
    from jidou.database import get_session
    from jidou.models.task import TaskStatus

    mock_task = _make_task(celery_task_id="orphan-id", status=TaskStatus.PENDING.value)
    updated: list[str] = []

    async def fake_create(session, task_id, task_type, **kwargs):  # type: ignore[no-untyped-def]
        return mock_task

    async def fake_update(session, task_id, status, **kwargs):  # type: ignore[no-untyped-def]
        updated.append(status.value)

    mock_scan = MagicMock()
    mock_scan.apply_async.side_effect = ConnectionError("broker unreachable")

    app.dependency_overrides[get_session] = _session_override(mock_task)
    try:
        with (
            patch("jidou.services.progress.create_task_record", side_effect=fake_create),
            patch("jidou.services.progress.update_task_status", side_effect=fake_update),
            patch("jidou.workers.scan_tasks.scan_remote_task", mock_scan),
        ):
            client = TestClient(app)
            response = client.post("/api/tasks/trigger", json={"task_type": "scan"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert updated == [TaskStatus.FAILED.value]


# ---------------------------------------------------------------------------
# TaskProgress schema — _coerce_task_status
# ---------------------------------------------------------------------------


def test_task_progress_schema_coerces_valid_status() -> None:
    """TaskProgress accepts a valid status string via field_validator."""
    from jidou.schemas.task_schema import TaskProgress

    tp = TaskProgress(
        celery_task_id="abc",
        status="running",
        progress_current=5,
        progress_total=10,
        progress_message="In progress",
    )
    assert tp.status == TaskStatus.RUNNING


def test_task_progress_schema_defaults_unknown_status_to_pending() -> None:
    """TaskProgress coerces an unknown status string to PENDING."""
    from jidou.schemas.task_schema import TaskProgress

    tp = TaskProgress(
        celery_task_id="abc",
        status="not_a_real_status",
        progress_current=0,
        progress_total=0,
        progress_message=None,
    )
    assert tp.status == TaskStatus.PENDING

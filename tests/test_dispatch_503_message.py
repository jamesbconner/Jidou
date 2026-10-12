"""Every broker-dispatch failure answers 503 with one detail string (roadmap DF-1 / D7)."""

from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jidou.database import get_session
from jidou.main import app

_DETAIL = "Task broker unavailable"

# (url, request kwargs, worker task patch target, needs RSS remote path configured)
_CASES: list[tuple[str, dict[str, Any], str, bool]] = [
    (
        "/api/tasks/trigger",
        {"json": {"task_type": "scan"}},
        "jidou.workers.scan_tasks.scan_remote_task",
        False,
    ),
    (
        "/api/import/text",
        {
            "data": {"content_type": "anime", "dry_run": False},
            "files": {"file": ("paths.txt", b"Z:\\anime tv\\Show\\S01E01.mkv\n", "text/plain")},
        },
        "jidou.workers.import_tasks.path_import_task",
        False,
    ),
    (
        "/api/import/database",
        {
            "files": {
                "file": (
                    "backup.json",
                    b'{"version": "1", "shows": [], "episodes": [], "watchlist": []}',
                    "application/json",
                )
            }
        },
        "jidou.workers.db_import_tasks.db_import_task",
        False,
    ),
    ("/api/rss/import", {}, "jidou.workers.rss_tasks.rss_import_task", True),
    ("/api/rss/publish", {}, "jidou.workers.rss_tasks.rss_publish_task", True),
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient with the DB session replaced by an inert async mock."""

    async def _session() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_session] = _session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_case_list_covers_every_dispatching_route() -> None:
    """Guard against a vacuous parametrization: all five dispatching routes are named."""
    assert _CASES
    assert {case[0] for case in _CASES} == {
        "/api/tasks/trigger",
        "/api/import/text",
        "/api/import/database",
        "/api/rss/import",
        "/api/rss/publish",
    }


@pytest.mark.parametrize(
    ("url", "kwargs", "target", "needs_rss_path"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_broker_failure_returns_unified_503(
    client: TestClient,
    url: str,
    kwargs: dict[str, Any],
    target: str,
    needs_rss_path: bool,
) -> None:
    """A failing broker yields 503 with exactly ``Task broker unavailable``."""
    request_kwargs = dict(kwargs)
    if "files" in kwargs:
        request_kwargs["files"] = {
            key: (name, BytesIO(body), ctype)
            for key, (name, body, ctype) in kwargs["files"].items()
        }
    with (
        patch("jidou.services.task_dispatch.create_task_record", new=AsyncMock()),
        patch("jidou.services.task_dispatch.update_task_status", new=AsyncMock()),
        patch(target) as mock_worker,
        patch("jidou.api.routes.rss_publish.settings") as mock_settings,
    ):
        mock_settings.rss_config_remote_path = "/remote/yarss2.conf" if needs_rss_path else None
        mock_worker.apply_async = MagicMock(side_effect=ConnectionError("broker down"))
        resp = client.post(url, **request_kwargs)

    assert resp.status_code == 503
    assert resp.json()["detail"] == _DETAIL

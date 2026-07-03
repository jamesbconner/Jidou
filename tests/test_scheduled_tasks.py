"""Tests for beat-scheduled overlap-guard tasks."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(active_count: int = 0) -> MagicMock:
    """Return a minimal async session stub that reports *active_count* active tasks.

    ``scalar_one`` is used by the COUNT check; ``scalar_one_or_none`` is used
    by ``create_task_record``'s SELECT — returns None so the insert path runs.
    """
    session = MagicMock()
    result = MagicMock()
    result.scalar_one.return_value = active_count
    result.scalar_one_or_none.return_value = None  # no pre-existing task record
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _patch_db(active_count: int = 0):
    """Context-manager pair that patches DB engine/session for scheduled_tasks."""
    session = _make_session(active_count)
    session_factory = MagicMock(return_value=session)

    engine = MagicMock()
    engine.dispose = AsyncMock()

    def fake_session_maker(*_: Any, **__: Any) -> MagicMock:
        return session_factory()

    return (
        patch("jidou.workers.scheduled_tasks.create_async_engine", return_value=engine),
        patch(
            "jidou.workers.scheduled_tasks.async_sessionmaker",
            return_value=fake_session_maker,
        ),
    )


# ---------------------------------------------------------------------------
# _try_claim_task
# ---------------------------------------------------------------------------


class TestTryClaimTask:
    @pytest.mark.asyncio
    async def test_returns_false_when_active_task_exists(self) -> None:
        """Guard detects an in-flight task and returns False (skip dispatch)."""
        from jidou.workers.scheduled_tasks import _try_claim_task

        p1, p2 = _patch_db(active_count=1)
        with p1, p2:
            assert await _try_claim_task("sync", "test-id") is False

    @pytest.mark.asyncio
    async def test_returns_true_and_inserts_row_when_clear(self) -> None:
        """When pipeline is clear, inserts a pending row and returns True."""
        from jidou.workers.scheduled_tasks import _try_claim_task

        p1, p2 = _patch_db(active_count=0)
        with p1, p2:
            result = await _try_claim_task("sync", "test-id")
        assert result is True

    @pytest.mark.asyncio
    async def test_commits_after_insert(self) -> None:
        """The pending row must be committed before the function returns."""
        from jidou.workers.scheduled_tasks import _try_claim_task

        session = _make_session(active_count=0)
        session_factory = MagicMock(return_value=session)
        engine = MagicMock()
        engine.dispose = AsyncMock()

        def fake_session_maker(*_: Any, **__: Any) -> MagicMock:
            return session_factory()

        with (
            patch("jidou.workers.scheduled_tasks.create_async_engine", return_value=engine),
            patch(
                "jidou.workers.scheduled_tasks.async_sessionmaker",
                return_value=fake_session_maker,
            ),
        ):
            await _try_claim_task("sync", "test-id")

        session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# scheduled_sync_task
# ---------------------------------------------------------------------------


class TestScheduledSyncTask:
    def test_skips_when_sync_is_active(self) -> None:
        """Guard fires and returns 'skipped' when a sync task is already running."""
        p1, p2 = _patch_db(active_count=1)
        with p1, p2:
            from jidou.workers.scheduled_tasks import scheduled_sync_task

            result = scheduled_sync_task()  # type: ignore[call-arg]
        assert result == "skipped"

    def test_dispatches_when_no_active_sync(self) -> None:
        """Dispatches sync_all_task and returns a UUID task ID when pipeline is clear."""
        p1, p2 = _patch_db(active_count=0)
        with (
            p1,
            p2,
            patch(
                "jidou.workers.scheduled_tasks._scheduled_sync",
                new_callable=AsyncMock,
                return_value="fake-uuid",
            ),
        ):
            from jidou.workers.scheduled_tasks import scheduled_sync_task

            result = scheduled_sync_task()  # type: ignore[call-arg]
        assert result == "fake-uuid"

    def test_dispatches_with_dry_run_false(self) -> None:
        """The dispatched sync task always receives dry_run=False from scheduler."""
        dispatched_args: list[Any] = []

        async def fake_scheduled_sync() -> str:
            from jidou.workers.sync_tasks import sync_all_task

            sync_all_task.apply_async(args=[False], task_id="test-id")
            dispatched_args.extend([False])
            return "test-id"

        p1, p2 = _patch_db(active_count=0)
        mock_apply = MagicMock()
        with (
            p1,
            p2,
            patch("jidou.workers.sync_tasks.sync_all_task") as mock_sync,
            patch(
                "jidou.workers.scheduled_tasks._scheduled_sync",
                side_effect=fake_scheduled_sync,
            ),
        ):
            mock_sync.apply_async = mock_apply
            from jidou.workers.scheduled_tasks import scheduled_sync_task

            scheduled_sync_task()  # type: ignore[call-arg]

        assert dispatched_args == [False]


# ---------------------------------------------------------------------------
# scheduled_rss_import_task
# ---------------------------------------------------------------------------


class TestScheduledRssImportTask:
    def test_skips_when_rss_import_is_active(self) -> None:
        """Guard skips when an rss_import task is already running."""
        p1, p2 = _patch_db(active_count=1)
        with p1, p2:
            from jidou.workers.scheduled_tasks import scheduled_rss_import_task

            result = scheduled_rss_import_task()  # type: ignore[call-arg]
        assert result == "skipped"

    def test_dispatches_when_no_active_rss_import(self) -> None:
        """Dispatches rss_import_task and returns a UUID task ID when clear."""
        p1, p2 = _patch_db(active_count=0)
        with (
            p1,
            p2,
            patch(
                "jidou.workers.scheduled_tasks._scheduled_rss_import",
                new_callable=AsyncMock,
                return_value="fake-uuid",
            ),
        ):
            from jidou.workers.scheduled_tasks import scheduled_rss_import_task

            result = scheduled_rss_import_task()  # type: ignore[call-arg]
        assert result == "fake-uuid"


# ---------------------------------------------------------------------------
# Beat schedule wiring
# ---------------------------------------------------------------------------


class TestBeatScheduleWiring:
    def test_beat_schedule_empty_when_both_disabled(self) -> None:
        """No beat schedule entries when both schedules are disabled (default)."""
        # Default settings have both schedules disabled
        from jidou.config import settings
        from jidou.workers.celery_app import celery_app

        if not settings.sync_schedule_enabled and not settings.rss_import_schedule_enabled:
            assert celery_app.conf.beat_schedule == {}

    def test_scheduled_tasks_registered_in_celery(self) -> None:
        """Both scheduled wrapper tasks must be discoverable in the Celery registry."""
        from jidou.workers.celery_app import celery_app

        names = celery_app.tasks
        assert any("scheduled_sync_task" in n for n in names)
        assert any("scheduled_rss_import_task" in n for n in names)

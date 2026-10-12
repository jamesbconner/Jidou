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

    ``scalar_one_or_none`` is called twice: first by ``get_active_task`` (an
    active row when *active_count* > 0, else None), then by
    ``create_task_record``'s SELECT (None, so the insert path runs).
    """
    session = MagicMock()
    result = MagicMock()
    active_row = MagicMock() if active_count else None
    result.scalar_one_or_none.side_effect = [active_row, None, None]
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
        patch("jidou.database.create_async_engine", return_value=engine),
        patch(
            "jidou.database.async_sessionmaker",
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
            patch("jidou.database.create_async_engine", return_value=engine),
            patch(
                "jidou.database.async_sessionmaker",
                return_value=fake_session_maker,
            ),
        ):
            await _try_claim_task("sync", "test-id")

        session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# _dispatch_scheduled — orphan cleanup on apply_async failure
# ---------------------------------------------------------------------------


class TestDispatchScheduled:
    @pytest.mark.asyncio
    async def test_deletes_pending_row_when_apply_async_raises(self) -> None:
        """If apply_async fails, the pre-created pending row must be removed."""
        from jidou.workers.scheduled_tasks import _dispatch_scheduled

        mock_task = MagicMock()
        mock_task.apply_async = MagicMock(side_effect=RuntimeError("broker down"))

        with (
            patch(
                "jidou.workers.scheduled_tasks._delete_task_record",
                new_callable=AsyncMock,
            ) as mock_delete,
            pytest.raises(RuntimeError, match="broker down"),
        ):
            await _dispatch_scheduled("sync", mock_task, "dead-id")

        mock_delete.assert_awaited_once_with("dead-id")

    @pytest.mark.asyncio
    async def test_returns_task_id_on_success(self) -> None:
        """Returns the task_id when apply_async succeeds."""
        from jidou.workers.scheduled_tasks import _dispatch_scheduled

        mock_task = MagicMock()
        mock_task.apply_async = MagicMock()

        result = await _dispatch_scheduled("sync", mock_task, "ok-id")

        assert result == "ok-id"
        mock_task.apply_async.assert_called_once()


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

    def test_real_dispatch_passes_dry_run_false(self) -> None:
        """The real _scheduled_sync calls apply_async(args=[False]) on the Celery task."""
        mock_task = MagicMock()
        mock_task.apply_async = MagicMock()

        p1, p2 = _patch_db(active_count=0)
        with (
            p1,
            p2,
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("jidou.workers.sync_tasks.sync_all_task", mock_task),
        ):
            from jidou.workers.scheduled_tasks import scheduled_sync_task

            scheduled_sync_task()  # type: ignore[call-arg]

        mock_task.apply_async.assert_called_once()
        _, kwargs = mock_task.apply_async.call_args
        assert kwargs["args"] == [False]


# ---------------------------------------------------------------------------
# scheduled_rss_import_task
# ---------------------------------------------------------------------------


class TestScheduledRssImportTask:
    def test_skips_when_rss_config_path_not_set(self) -> None:
        """Skips without claiming a slot when RSS_CONFIG_REMOTE_PATH is not configured."""
        with patch("jidou.workers.scheduled_tasks.settings") as mock_settings:
            mock_settings.rss_config_remote_path = ""
            from jidou.workers.scheduled_tasks import scheduled_rss_import_task

            result = scheduled_rss_import_task()  # type: ignore[call-arg]
        assert result == "skipped"

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
    def test_beat_schedule_only_contains_enabled_schedules(self) -> None:
        """Beat schedule keys reflect exactly which schedules are enabled."""
        from jidou.config import settings
        from jidou.workers.celery_app import celery_app

        expected_keys = set()
        if settings.sync_schedule_enabled:
            expected_keys.add("scheduled-sync")
        if settings.rss_import_schedule_enabled:
            expected_keys.add("scheduled-rss-import")
        if settings.image_cache_expiration_enabled:
            expected_keys.add("purge-stale-images")

        assert set(celery_app.conf.beat_schedule.keys()) == expected_keys

    def test_scheduled_tasks_registered_in_celery(self) -> None:
        """Both scheduled wrapper tasks must be discoverable in the Celery registry."""
        from jidou.workers.celery_app import celery_app

        names = celery_app.tasks
        assert any("scheduled_sync_task" in n for n in names)
        assert any("scheduled_rss_import_task" in n for n in names)


# ---------------------------------------------------------------------------
# _delete_task_record — engine-lifecycle error semantics
# ---------------------------------------------------------------------------


class TestDeleteTaskRecord:
    @pytest.mark.asyncio
    async def test_engine_creation_failure_is_logged_not_raised(self) -> None:
        """Best-effort cleanup: a failure creating the engine is swallowed."""
        from jidou.workers.scheduled_tasks import _delete_task_record

        with patch("jidou.database.create_async_engine", side_effect=OSError("no engine")):
            await _delete_task_record("orphan-id")  # must not raise

    @pytest.mark.asyncio
    async def test_dispose_failure_propagates(self) -> None:
        """Disposal runs after the swallow block, so its failure still propagates."""
        from jidou.workers.scheduled_tasks import _delete_task_record

        session = _make_session()
        engine = MagicMock()
        engine.dispose = AsyncMock(side_effect=OSError("dispose failed"))

        with (
            patch("jidou.database.create_async_engine", return_value=engine),
            patch(
                "jidou.database.async_sessionmaker", return_value=MagicMock(return_value=session)
            ),
            pytest.raises(OSError, match="dispose failed"),
        ):
            await _delete_task_record("orphan-id")

        session.commit.assert_awaited()


# ---------------------------------------------------------------------------
# Characterization: scheduled dispatch flow (skip reasons, log lines, task types)
# ---------------------------------------------------------------------------

_LOGGER_NAME = "jidou.workers.scheduled_tasks"


class TestScheduledFlowCharacterization:
    """Pin the claim -> lazy import -> dispatch sequence of each scheduled task."""

    @pytest.mark.asyncio
    async def test_sync_skips_with_info_log_when_claim_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from jidou.workers.scheduled_tasks import _scheduled_sync

        with (
            caplog.at_level("INFO", logger=_LOGGER_NAME),
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=False,
            ) as claim,
            patch(
                "jidou.workers.scheduled_tasks._dispatch_scheduled", new_callable=AsyncMock
            ) as dispatch,
        ):
            assert await _scheduled_sync() == "skipped"

        assert claim.await_args is not None
        assert claim.await_args.args[0] == "sync"
        dispatch.assert_not_awaited()
        records = [r for r in caplog.records if r.name == _LOGGER_NAME]
        assert [(r.levelname, r.getMessage()) for r in records] == [
            ("INFO", "Scheduled sync skipped: a sync task is already active")
        ]

    @pytest.mark.asyncio
    async def test_sync_dispatches_sync_all_task_with_claimed_id(self) -> None:
        from jidou.workers.scheduled_tasks import _scheduled_sync
        from jidou.workers.sync_tasks import sync_all_task

        with (
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=True,
            ) as claim,
            patch(
                "jidou.workers.scheduled_tasks._dispatch_scheduled",
                new_callable=AsyncMock,
                return_value="the-id",
            ) as dispatch,
        ):
            assert await _scheduled_sync() == "the-id"

        assert claim.await_args is not None
        claimed_id = claim.await_args.args[1]
        dispatch.assert_awaited_once_with("sync", sync_all_task, claimed_id)

    @pytest.mark.asyncio
    async def test_rss_skips_with_warning_before_claim_when_path_unset(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from jidou.workers.scheduled_tasks import _scheduled_rss_import

        with (
            caplog.at_level("INFO", logger=_LOGGER_NAME),
            patch("jidou.workers.scheduled_tasks.settings") as mock_settings,
            patch("jidou.workers.scheduled_tasks._try_claim_task", new_callable=AsyncMock) as claim,
        ):
            mock_settings.rss_config_remote_path = ""
            assert await _scheduled_rss_import() == "skipped"

        claim.assert_not_awaited()
        records = [r for r in caplog.records if r.name == _LOGGER_NAME]
        assert [(r.levelname, r.getMessage()) for r in records] == [
            ("WARNING", "Scheduled RSS import skipped: RSS_CONFIG_REMOTE_PATH is not configured")
        ]

    @pytest.mark.asyncio
    async def test_rss_skips_with_info_log_when_claim_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from jidou.workers.scheduled_tasks import _scheduled_rss_import

        with (
            caplog.at_level("INFO", logger=_LOGGER_NAME),
            patch("jidou.workers.scheduled_tasks.settings") as mock_settings,
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=False,
            ) as claim,
            patch(
                "jidou.workers.scheduled_tasks._dispatch_scheduled", new_callable=AsyncMock
            ) as dispatch,
        ):
            mock_settings.rss_config_remote_path = "/remote/rss.json"
            assert await _scheduled_rss_import() == "skipped"

        assert claim.await_args is not None
        assert claim.await_args.args[0] == "rss_import"
        dispatch.assert_not_awaited()
        records = [r for r in caplog.records if r.name == _LOGGER_NAME]
        assert [(r.levelname, r.getMessage()) for r in records] == [
            ("INFO", "Scheduled RSS import skipped: an rss_import task is already active")
        ]

    @pytest.mark.asyncio
    async def test_rss_dispatches_rss_import_task_with_claimed_id(self) -> None:
        from jidou.workers.rss_tasks import rss_import_task
        from jidou.workers.scheduled_tasks import _scheduled_rss_import

        with (
            patch("jidou.workers.scheduled_tasks.settings") as mock_settings,
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=True,
            ) as claim,
            patch(
                "jidou.workers.scheduled_tasks._dispatch_scheduled",
                new_callable=AsyncMock,
                return_value="rss-id",
            ) as dispatch,
        ):
            mock_settings.rss_config_remote_path = "/remote/rss.json"
            assert await _scheduled_rss_import() == "rss-id"

        assert claim.await_args is not None
        dispatch.assert_awaited_once_with("rss_import", rss_import_task, claim.await_args.args[1])

    @pytest.mark.asyncio
    async def test_claim_inserts_pending_row_with_task_type_and_no_dry_run(self) -> None:
        from jidou.workers.scheduled_tasks import _try_claim_task

        p1, p2 = _patch_db(active_count=0)
        with (
            p1,
            p2,
            patch(
                "jidou.workers.scheduled_tasks.create_task_record", new_callable=AsyncMock
            ) as create,
        ):
            assert await _try_claim_task("rss_import", "new-id") is True

        assert create.await_args is not None
        assert create.await_args.args[1:] == ("new-id", "rss_import")
        assert create.await_args.kwargs == {"dry_run": False}

    @pytest.mark.asyncio
    async def test_claim_does_not_insert_when_active(self) -> None:
        from jidou.workers.scheduled_tasks import _try_claim_task

        p1, p2 = _patch_db(active_count=1)
        with (
            p1,
            p2,
            patch(
                "jidou.workers.scheduled_tasks.create_task_record", new_callable=AsyncMock
            ) as create,
        ):
            assert await _try_claim_task("rss_import", "new-id") is False

        create.assert_not_awaited()

    def test_celery_names_are_unchanged(self) -> None:
        from jidou.workers.scheduled_tasks import scheduled_rss_import_task, scheduled_sync_task

        assert scheduled_sync_task.name == "jidou.workers.scheduled_tasks.scheduled_sync_task"
        assert (
            scheduled_rss_import_task.name
            == "jidou.workers.scheduled_tasks.scheduled_rss_import_task"
        )


# ---------------------------------------------------------------------------
# _run_scheduled
# ---------------------------------------------------------------------------


class TestRunScheduled:
    @pytest.mark.asyncio
    async def test_skip_reason_short_circuits_before_claim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A precondition message is logged as a warning; no slot is claimed or loaded."""
        from jidou.workers.scheduled_tasks import _run_scheduled

        load_task = MagicMock()
        with (
            caplog.at_level("INFO", logger=_LOGGER_NAME),
            patch("jidou.workers.scheduled_tasks._try_claim_task", new_callable=AsyncMock) as claim,
        ):
            result = await _run_scheduled(
                "demo",
                load_task,
                claim_skipped_message="unused",
                skip_reason=lambda: "not configured",
            )

        assert result == "skipped"
        claim.assert_not_awaited()
        load_task.assert_not_called()
        assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
            ("WARNING", "not configured")
        ]

    @pytest.mark.asyncio
    async def test_skip_reason_returning_none_proceeds_to_claim(self) -> None:
        from jidou.workers.scheduled_tasks import _run_scheduled

        celery_task = MagicMock()
        with (
            patch(
                "jidou.workers.scheduled_tasks._try_claim_task",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "jidou.workers.scheduled_tasks._dispatch_scheduled",
                new_callable=AsyncMock,
                return_value="x",
            ) as dispatch,
        ):
            result = await _run_scheduled(
                "demo", lambda: celery_task, claim_skipped_message="m", skip_reason=lambda: None
            )

        assert result == "x"
        assert dispatch.await_args is not None
        assert dispatch.await_args.args[:2] == ("demo", celery_task)

    @pytest.mark.asyncio
    async def test_load_task_not_called_when_claim_fails(self) -> None:
        from jidou.workers.scheduled_tasks import _run_scheduled

        load_task = MagicMock()
        with patch(
            "jidou.workers.scheduled_tasks._try_claim_task",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await _run_scheduled("demo", load_task, claim_skipped_message="m")

        assert result == "skipped"
        load_task.assert_not_called()

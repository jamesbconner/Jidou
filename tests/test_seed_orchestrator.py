"""Tests for SeedOrchestrator and seed_remote_task."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.models.downloaded_file import FileStatus
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_remote_file(name: str, path: str, size: int = 1_000_000) -> MagicMock:
    rf = MagicMock()
    rf.name = name
    rf.path = path
    rf.size = size
    return rf


class _FakeSession:
    """Minimal async session stub for SeedOrchestrator tests."""

    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self._existing: dict[str, str] = existing or {}
        self.added: list[Any] = []
        self.commits = 0
        self._nested_ctx: _FakeNested | None = None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self) -> _FakeNested:
        self._nested_ctx = _FakeNested(self)
        return self._nested_ctx

    async def execute(self, stmt: Any) -> _FakeResult:
        # Return rows matching the IN() clause that SeedOrchestrator builds.
        # We can't parse SQLAlchemy Core constructs directly, so we return
        # all known existing rows and let the orchestrator filter them.
        rows = [_FakeRow(path, status) for path, status in self._existing.items()]
        return _FakeResult(rows)


class _FakeNested:
    """Minimal async context manager for begin_nested()."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeNested:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False  # propagate exceptions


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeRow:
    def __init__(self, remote_path: str, status: str) -> None:
        self.remote_path = remote_path
        self.status = status


# ---------------------------------------------------------------------------
# SeedOrchestrator unit tests
# ---------------------------------------------------------------------------


class TestSeedOrchestrator:
    """Unit tests for SeedOrchestrator.run()."""

    def _make_sftp(self, files: list[MagicMock]) -> MagicMock:
        sftp = MagicMock()
        sftp.list_remote_files_recursive = AsyncMock(return_value=files)
        return sftp

    @pytest.mark.asyncio
    async def test_happy_path_seeds_new_files(self) -> None:
        """Files not in DB should be inserted with status SEEDED."""
        files = [
            _make_remote_file("show.s01e01.mkv", "/sftp/show/show.s01e01.mkv"),
            _make_remote_file("show.s01e02.mkv", "/sftp/show/show.s01e02.mkv"),
        ]
        sftp = self._make_sftp(files)
        session = _FakeSession()

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 2
        assert result.files_seeded == 2
        assert result.files_skipped == 0
        assert result.paths_scanned == 1
        assert result.paths_failed == 0
        assert result.dry_run is False
        # One DownloadedFile per new file should have been staged
        assert len(session.added) == 2
        for obj in session.added:
            assert obj.status == FileStatus.SEEDED
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_skips_existing_regardless_of_status(self) -> None:
        """Files already in the DB are skipped no matter what their status is."""
        existing_path = "/sftp/show/show.s01e01.mkv"
        files = [_make_remote_file("show.s01e01.mkv", existing_path)]
        sftp = self._make_sftp(files)
        session = _FakeSession(existing={existing_path: "downloaded"})

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 1
        assert result.files_seeded == 0
        assert result.files_skipped == 1
        assert result.skipped_by_status == {"downloaded": 1}
        assert session.added == []

    @pytest.mark.asyncio
    async def test_skips_seeded_status_on_rerun(self) -> None:
        """Re-running skips rows that are already SEEDED — idempotent."""
        path = "/sftp/show/ep01.mkv"
        files = [_make_remote_file("ep01.mkv", path)]
        sftp = self._make_sftp(files)
        session = _FakeSession(existing={path: "seeded"})

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_seeded == 0
        assert result.files_skipped == 1
        assert result.skipped_by_status == {"seeded": 1}

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(self) -> None:
        """Dry run logs but makes no inserts or commits."""
        files = [_make_remote_file("ep01.mkv", "/sftp/show/ep01.mkv")]
        sftp = self._make_sftp(files)
        session = _FakeSession()

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=True)

        assert result.dry_run is True
        assert result.files_seeded == 1
        assert session.added == []
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_listing_failure_counts_path_failed(self) -> None:
        """A listing failure on one path increments paths_failed and continues."""
        sftp = MagicMock()
        sftp.list_remote_files_recursive = AsyncMock(side_effect=OSError("Connection refused"))
        session = _FakeSession()

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.paths_failed == 1
        assert result.files_found == 0
        assert result.files_seeded == 0

    @pytest.mark.asyncio
    async def test_empty_remote_returns_zero_result(self) -> None:
        """Empty SFTP inventory produces a zero SeedResult with no DB activity."""
        sftp = self._make_sftp([])
        session = _FakeSession()

        result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 0
        assert result.files_seeded == 0
        assert result.files_skipped == 0
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_on_progress_called_after_each_batch(self) -> None:
        """on_progress callback is invoked at least once per batch during seeding."""
        files = [_make_remote_file(f"ep{i:02d}.mkv", f"/sftp/ep{i:02d}.mkv") for i in range(5)]
        sftp = self._make_sftp(files)
        session = _FakeSession()
        progress_calls: list[tuple[int, int, str]] = []

        async def on_progress(current: int, total: int, message: str) -> None:
            progress_calls.append((current, total, message))

        result = await SeedOrchestrator(session, sftp, ["/sftp"], batch_size=2).run(
            dry_run=False, on_progress=on_progress
        )

        assert result.files_seeded == 5
        # 5 files with batch_size=2 → 3 batches → 3 progress calls (insert phase only)
        assert len(progress_calls) == 3
        # All calls use total_pending as denominator — no mid-run scale switch
        totals = {total for _, total, _ in progress_calls}
        assert totals == {5}

    @pytest.mark.asyncio
    async def test_multiple_remote_paths(self) -> None:
        """Files from multiple remote paths are all collected and seeded."""
        sftp = MagicMock()
        sftp.list_remote_files_recursive = AsyncMock(
            side_effect=[
                [_make_remote_file("ep01.mkv", "/tv/ep01.mkv")],
                [_make_remote_file("ep02.mkv", "/anime/ep02.mkv")],
            ]
        )
        session = _FakeSession()

        result = await SeedOrchestrator(session, sftp, ["/tv", "/anime"]).run(dry_run=False)

        assert result.paths_scanned == 2
        assert result.files_found == 2
        assert result.files_seeded == 2

    def test_seeded_not_referenced_in_download_orchestrator(self) -> None:
        """Regression: download_orchestrator source must not reference SEEDED in its
        query conditions — seeded files must never be picked up for download.
        """
        import inspect

        from jidou.orchestrators import download_orchestrator

        source = inspect.getsource(download_orchestrator)
        # 'SEEDED' should not appear anywhere in the download orchestrator's
        # query-building code (other than a comment explaining exclusion, if any).
        # We look for it in a status-comparison context.
        assert "FileStatus.SEEDED" not in source, (
            "download_orchestrator references FileStatus.SEEDED — "
            "check that SEEDED files are not being picked up for download"
        )

    def test_seeded_not_referenced_in_match_orchestrator(self) -> None:
        """Regression: match_orchestrator source must not reference SEEDED in its
        query conditions — seeded files must never be sent through the match pipeline.
        """
        import inspect

        from jidou.orchestrators import match_orchestrator

        source = inspect.getsource(match_orchestrator)
        assert "FileStatus.SEEDED" not in source, (
            "match_orchestrator references FileStatus.SEEDED — "
            "check that SEEDED files are not being picked up for matching"
        )


# ---------------------------------------------------------------------------
# seed_remote_task Celery task tests
# ---------------------------------------------------------------------------


class TestSeedRemoteTask:
    """Unit tests for seed_remote_task."""

    def test_soft_timeout_calls_mark_timed_out(self) -> None:
        """SoftTimeLimitExceeded in seed_remote_task must call mark_task_timed_out."""
        from jidou.workers.seed_tasks import seed_remote_task

        mark_calls: list[str] = []

        async def fake_mark(celery_task_id: str) -> None:
            mark_calls.append(celery_task_id)

        with (
            patch(
                "jidou.workers.seed_tasks._seed_remote",
                new_callable=AsyncMock,
                side_effect=SoftTimeLimitExceeded(),
            ),
            patch("jidou.workers.seed_tasks.mark_task_timed_out", side_effect=fake_mark),
            pytest.raises(SoftTimeLimitExceeded),
        ):
            seed_remote_task()  # type: ignore[call-arg]

        assert len(mark_calls) == 1

    def test_seed_task_registered_in_celery(self) -> None:
        """seed_remote_task should be discoverable in the Celery task registry."""
        from jidou.workers.celery_app import celery_app

        registered = celery_app.tasks
        assert any("seed_remote_task" in name for name in registered)

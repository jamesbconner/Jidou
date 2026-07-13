"""Tests for SeedOrchestrator and seed_remote_task."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from jidou.models.downloaded_file import FileStatus
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators.seed_orchestrator import SeedOrchestrator
from jidou.services.sftp_service import RecursiveListResult, RemoteFile
from tests._fake_orchestrator_session import (
    FakeOrchestratorDB,
    FakeOrchestratorSession,
    make_chunked_existing_paths_fake,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(name: str, path: str, size: int = 1_000_000) -> RemoteFile:
    return RemoteFile(name=name, path=path, size=size, is_dir=False)


def _make_dir(name: str, path: str) -> RemoteFile:
    return RemoteFile(name=name, path=path, size=0, is_dir=True)


def _make_sftp(
    children_by_path: dict[str, list[RemoteFile]],
    walk_by_path: dict[str, RecursiveListResult | BaseException] | None = None,
) -> MagicMock:
    """Build a mock SFTPService matching SeedOrchestrator's new call pattern:
    one list_remote_children() per configured remote path, then ONE combined
    list_remote_files_recursive_batch() call across every top-level directory
    discovered across all paths.

    Args:
        children_by_path: remote_path -> list_remote_children() return value.
        walk_by_path: directory path -> RecursiveListResult (or an exception
            instance to simulate a failed deep walk) for that directory.
    """
    sftp = MagicMock()

    async def _children(path: str | None = None) -> list[RemoteFile]:
        return children_by_path.get(path, [])

    sftp.list_remote_children = AsyncMock(side_effect=_children)

    walk_by_path = walk_by_path or {}

    async def _batch(
        paths: list[str], pattern: str = "*"
    ) -> list[tuple[str, RecursiveListResult | BaseException]]:
        return [(p, walk_by_path.get(p, RecursiveListResult(files=[]))) for p in paths]

    sftp.list_remote_files_recursive_batch = AsyncMock(side_effect=_batch)
    return sftp


def _patch_chunked_existing(db: FakeOrchestratorDB | None = None):
    """Patch chunked_existing_paths (imported into seed_orchestrator.py) against *db*."""
    db = db or FakeOrchestratorDB()
    return patch(
        "jidou.orchestrators.seed_orchestrator.chunked_existing_paths",
        new=make_chunked_existing_paths_fake(db),
    )


# ---------------------------------------------------------------------------
# SeedOrchestrator unit tests — file seeding
# ---------------------------------------------------------------------------


class TestSeedOrchestrator:
    """Unit tests for SeedOrchestrator.run()."""

    @pytest.mark.asyncio
    async def test_happy_path_seeds_new_files_at_root(self) -> None:
        """Files sitting directly at the configured root (no subdirectory) are seeded."""
        files = [
            _make_file("show.s01e01.mkv", "/sftp/show/show.s01e01.mkv"),
            _make_file("show.s01e02.mkv", "/sftp/show/show.s01e02.mkv"),
        ]
        sftp = _make_sftp(children_by_path={"/sftp/show": files})
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 2
        assert result.files_seeded == 2
        assert result.files_skipped == 0
        assert result.paths_scanned == 1
        assert result.paths_failed == 0
        assert result.dry_run is False
        assert len([o for o in session.added if hasattr(o, "status")]) == 2
        for obj in session.added:
            assert obj.status == FileStatus.SEEDED

    @pytest.mark.asyncio
    async def test_files_inside_new_directory_are_deep_walked_and_seeded(self) -> None:
        """Files under a newly-discovered top-level directory are found via the batch deep walk."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        files = [
            _make_file("ep01.mkv", "/sftp/show/Show A/ep01.mkv"),
            _make_file("ep02.mkv", "/sftp/show/Show A/ep02.mkv"),
        ]
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=files)},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 2
        assert result.files_seeded == 2
        sftp.list_remote_files_recursive_batch.assert_called_once_with(["/sftp/show/Show A"])

    @pytest.mark.asyncio
    async def test_batch_insert_race_loss_counts_as_skipped(self) -> None:
        """A concurrent scan winning the insert race during the batch loop is
        counted as skipped, not seeded."""
        files = [_make_file("ep01.mkv", "/sftp/show/ep01.mkv")]
        sftp = _make_sftp(children_by_path={"/sftp/show": files})
        session = FakeOrchestratorSession()

        with (
            _patch_chunked_existing(),
            patch(
                "jidou.orchestrators.seed_orchestrator.insert_or_skip_duplicate",
                new=AsyncMock(return_value=False),
            ),
        ):
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_seeded == 0
        assert result.files_skipped == 1
        assert result.skipped_by_status == {"discovered": 1}

    @pytest.mark.asyncio
    async def test_skips_existing_regardless_of_status(self) -> None:
        """Files already in the DB are skipped no matter what their status is."""
        existing_path = "/sftp/show/show.s01e01.mkv"
        files = [_make_file("show.s01e01.mkv", existing_path)]
        sftp = _make_sftp(children_by_path={"/sftp/show": files})
        db = FakeOrchestratorDB(existing_files={existing_path: "downloaded"})
        session = FakeOrchestratorSession(db)

        with _patch_chunked_existing(db):
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
        files = [_make_file("ep01.mkv", path)]
        sftp = _make_sftp(children_by_path={"/sftp/show": files})
        db = FakeOrchestratorDB(existing_files={path: "seeded"})
        session = FakeOrchestratorSession(db)

        with _patch_chunked_existing(db):
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_seeded == 0
        assert result.files_skipped == 1
        assert result.skipped_by_status == {"seeded": 1}

    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(self) -> None:
        """Dry run logs but makes no inserts or commits, for files or directories."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        files = [_make_file("ep01.mkv", "/sftp/show/Show A/ep01.mkv")]
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=files)},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=True)

        assert result.dry_run is True
        assert result.files_seeded == 1
        assert session.added == []
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_listing_failure_counts_path_failed(self) -> None:
        """A shallow-listing failure on one path increments paths_failed and continues."""
        sftp = MagicMock()
        sftp.list_remote_children = AsyncMock(side_effect=OSError("Connection refused"))
        sftp.list_remote_files_recursive_batch = AsyncMock(return_value=[])
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.paths_failed == 1
        assert result.files_found == 0
        assert result.files_seeded == 0

    @pytest.mark.asyncio
    async def test_empty_remote_returns_zero_result(self) -> None:
        """Empty SFTP inventory produces a zero SeedResult with no DB activity."""
        sftp = _make_sftp(children_by_path={"/sftp/show": []})
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 0
        assert result.files_seeded == 0
        assert result.files_skipped == 0
        assert session.commits == 0

    @pytest.mark.asyncio
    async def test_on_progress_called_after_each_file_batch(self) -> None:
        """on_progress callback is invoked once per file-insert batch, not during walking."""
        files = [_make_file(f"ep{i:02d}.mkv", f"/sftp/ep{i:02d}.mkv") for i in range(5)]
        sftp = _make_sftp(children_by_path={"/sftp": files})
        session = FakeOrchestratorSession()
        progress_calls: list[tuple[int, int, str]] = []

        async def on_progress(current: int, total: int, message: str) -> None:
            progress_calls.append((current, total, message))

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp"], batch_size=2).run(
                dry_run=False, on_progress=on_progress
            )

        assert result.files_seeded == 5
        # 5 files with batch_size=2 → 3 batches → 3 progress calls (insert phase only)
        assert len(progress_calls) == 3
        totals = {total for _, total, _ in progress_calls}
        assert totals == {5}

    @pytest.mark.asyncio
    async def test_multiple_remote_paths_collected_and_walked_together(self) -> None:
        """Top-level dirs from multiple remote paths are deep-walked in ONE combined batch call."""
        tv_dir = _make_dir("Show TV", "/tv/Show TV")
        anime_dir = _make_dir("Show Anime", "/anime/Show Anime")
        sftp = _make_sftp(
            children_by_path={"/tv": [tv_dir], "/anime": [anime_dir]},
            walk_by_path={
                "/tv/Show TV": RecursiveListResult(
                    files=[_make_file("ep01.mkv", "/tv/Show TV/ep01.mkv")]
                ),
                "/anime/Show Anime": RecursiveListResult(
                    files=[_make_file("ep01.mkv", "/anime/Show Anime/ep01.mkv")]
                ),
            },
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/tv", "/anime"]).run(dry_run=False)

        assert result.paths_scanned == 2
        assert result.files_found == 2
        assert result.files_seeded == 2
        # Exactly one combined batch call across both configured paths' directories.
        sftp.list_remote_files_recursive_batch.assert_called_once()
        called_paths = sftp.list_remote_files_recursive_batch.call_args[0][0]
        assert set(called_paths) == {"/tv/Show TV", "/anime/Show Anime"}

    def test_seeded_not_referenced_in_download_orchestrator(self) -> None:
        """Regression: download_orchestrator source must not reference SEEDED in its
        query conditions — seeded files must never be picked up for download.
        """
        import inspect

        from jidou.orchestrators import download_orchestrator

        source = inspect.getsource(download_orchestrator)
        assert "FileStatus.SEEDED" not in source, (
            "download_orchestrator references FileStatus.SEEDED — "
            "check that SEEDED files are not being picked up for download"
        )

    def test_seeded_not_referenced_in_parse_orchestrator(self) -> None:
        """Regression: parse_orchestrator source must not reference SEEDED in its
        query conditions — seeded files must never be sent through the match pipeline.

        parse_orchestrator (via ParseOrchestrator) is the live match stage;
        the original match_orchestrator this test targeted was deleted as
        dead code (superseded by ParseOrchestrator, unreachable from any
        route or worker).
        """
        import inspect

        from jidou.orchestrators import parse_orchestrator

        source = inspect.getsource(parse_orchestrator)
        assert "FileStatus.SEEDED" not in source, (
            "parse_orchestrator references FileStatus.SEEDED — "
            "check that SEEDED files are not being picked up for matching"
        )


# ---------------------------------------------------------------------------
# SeedOrchestrator directory-marking (ScannedDirectory backfill) — see #355
# ---------------------------------------------------------------------------


class TestSeedOrchestratorDirectoryMarking:
    """ScannedDirectory backfill during seeding — see issue #355."""

    @pytest.mark.asyncio
    async def test_marks_one_scanned_directory_per_distinct_top_level_dir(self) -> None:
        """Multiple files under the same directory still produce exactly one marker."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        files = [
            _make_file("ep01.mkv", "/sftp/show/Show A/ep01.mkv"),
            _make_file("ep02.mkv", "/sftp/show/Show A/ep02.mkv"),
        ]
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=files)},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        markers = [o for o in session.added if isinstance(o, ScannedDirectory)]
        assert len(markers) == 1
        assert markers[0].remote_path == "/sftp/show/Show A"

    @pytest.mark.asyncio
    async def test_directory_with_zero_files_still_gets_marked(self) -> None:
        """A top-level directory with no eligible media files still gets a marker."""
        empty_dir = _make_dir("Empty Show", "/sftp/show/Empty Show")
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [empty_dir]},
            walk_by_path={"/sftp/show/Empty Show": RecursiveListResult(files=[])},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert result.files_found == 0
        markers = [o for o in session.added if isinstance(o, ScannedDirectory)]
        assert [m.remote_path for m in markers] == ["/sftp/show/Empty Show"]

    @pytest.mark.asyncio
    async def test_files_at_root_create_no_spurious_marker(self) -> None:
        """Files sitting directly at the remote root (no subdirectory) mark nothing."""
        files = [_make_file("special.mkv", "/sftp/show/special.mkv")]
        sftp = _make_sftp(children_by_path={"/sftp/show": files})  # no directories
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert not any(isinstance(o, ScannedDirectory) for o in session.added)

    @pytest.mark.asyncio
    async def test_rerun_is_idempotent_no_duplicate_markers(self) -> None:
        """A directory already marked known is not re-added on a second seed run."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=[])},
        )
        db = FakeOrchestratorDB(existing_dirs={"/sftp/show/Show A"})
        session = FakeOrchestratorSession(db)

        with _patch_chunked_existing(db):
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert not any(isinstance(o, ScannedDirectory) for o in session.added)

    @pytest.mark.asyncio
    async def test_failed_shallow_listing_skips_that_path_only(self) -> None:
        """A path whose shallow listing fails gets no directory marking; other paths still do."""
        good_dir = _make_dir("Good Show", "/good/Good Show")

        sftp = MagicMock()

        async def fake_children(path: str | None = None) -> list[RemoteFile]:
            if path == "/bad":
                raise OSError("connection refused")
            return [good_dir]

        sftp.list_remote_children = AsyncMock(side_effect=fake_children)
        sftp.list_remote_files_recursive_batch = AsyncMock(
            return_value=[("/good/Good Show", RecursiveListResult(files=[]))]
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/good", "/bad"]).run(dry_run=False)

        assert result.paths_failed == 1
        markers = [o for o in session.added if isinstance(o, ScannedDirectory)]
        assert [m.remote_path for m in markers] == ["/good/Good Show"]

    @pytest.mark.asyncio
    async def test_failed_deep_walk_skips_marking_that_directory_only(self) -> None:
        """A directory whose own deep walk raises gets no marker; sibling directories still do,
        even under the SAME configured remote path (per-directory granularity, not per-path)."""
        good_dir = _make_dir("Good Show", "/sftp/Good Show")
        bad_dir = _make_dir("Bad Show", "/sftp/Bad Show")
        sftp = _make_sftp(
            children_by_path={"/sftp": [good_dir, bad_dir]},
            walk_by_path={
                "/sftp/Good Show": RecursiveListResult(files=[]),
                "/sftp/Bad Show": RuntimeError("connection reset"),
            },
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp"]).run(dry_run=False)

        assert result.paths_failed == 0  # the shallow listing itself succeeded
        markers = [o for o in session.added if isinstance(o, ScannedDirectory)]
        assert [m.remote_path for m in markers] == ["/sftp/Good Show"]

    @pytest.mark.asyncio
    async def test_partial_walk_skips_marking_that_directory_only_not_whole_path(self) -> None:
        """A directory not fully walked isn't marked, but a SIBLING directory under the
        same configured remote path IS still marked -- regression test for the tree-wide
        fully_walked granularity bug (issue #355 follow-up): per-directory, not per-root."""
        fresh_dir = _make_dir("Still Downloading", "/sftp/Still Downloading")
        settled_dir = _make_dir("Settled Show", "/sftp/Settled Show")
        sftp = _make_sftp(
            children_by_path={"/sftp": [fresh_dir, settled_dir]},
            walk_by_path={
                "/sftp/Still Downloading": RecursiveListResult(files=[], io_failures=1),
                "/sftp/Settled Show": RecursiveListResult(files=[]),
            },
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            result = await SeedOrchestrator(session, sftp, ["/sftp"]).run(dry_run=False)

        assert result.paths_failed == 0
        markers = {o.remote_path for o in session.added if isinstance(o, ScannedDirectory)}
        assert markers == {"/sftp/Settled Show"}

    @pytest.mark.asyncio
    async def test_dry_run_marks_nothing(self) -> None:
        """dry_run inserts no ScannedDirectory rows."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=[])},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=True)

        assert session.added == []

    @pytest.mark.asyncio
    async def test_no_separate_shallow_listing_after_the_deep_walk(self) -> None:
        """Regression for the TOCTOU race (#355 follow-up): list_remote_children is called
        exactly once per configured remote path -- never a second time after the deep walk
        to re-discover directories, which was the old design's non-atomic race window."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=[])},
        )
        session = FakeOrchestratorSession()

        with _patch_chunked_existing():
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert sftp.list_remote_children.call_count == 1

    @pytest.mark.asyncio
    async def test_directory_markers_committed_strictly_after_file_batches(self) -> None:
        """Regression for the commit-ordering bug (#355 follow-up): ScannedDirectory rows
        must never appear in an earlier commit than the DownloadedFile rows for that
        directory's own files -- a crash between commits must never leave a directory
        marked known before its files exist."""
        show_dir = _make_dir("Show A", "/sftp/show/Show A")
        files = [_make_file("ep01.mkv", "/sftp/show/Show A/ep01.mkv")]
        sftp = _make_sftp(
            children_by_path={"/sftp/show": [show_dir]},
            walk_by_path={"/sftp/show/Show A": RecursiveListResult(files=files)},
        )
        session = FakeOrchestratorSession()

        commit_snapshots: list[list[object]] = []
        real_commit = session.commit

        async def tracking_commit() -> None:
            await real_commit()
            commit_snapshots.append(list(session.added))

        session.commit = tracking_commit  # type: ignore[method-assign]

        with _patch_chunked_existing():
            await SeedOrchestrator(session, sftp, ["/sftp/show"]).run(dry_run=False)

        assert len(commit_snapshots) == 2, "expected one commit for files, one for directories"
        # First commit: only the file row(s), no directory marker yet.
        assert not any(isinstance(o, ScannedDirectory) for o in commit_snapshots[0])
        # Final commit: the directory marker is now present, and every file
        # row from the first commit is still present too (files were never
        # rolled back or duplicated).
        final = commit_snapshots[-1]
        assert any(isinstance(o, ScannedDirectory) for o in final)
        assert len([o for o in final if hasattr(o, "status")]) == 1


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

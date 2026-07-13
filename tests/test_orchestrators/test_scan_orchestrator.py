"""Tests for ScanOrchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import DownloadedFile
from jidou.models.scanned_directory import ScannedDirectory
from jidou.orchestrators.scan_orchestrator import ScanOrchestrator
from jidou.services.sftp_service import RecursiveListResult, RemoteFile


def _make_file(name="episode.mkv", path="/remote/show/episode.mkv", size=1000) -> RemoteFile:
    return RemoteFile(name=name, path=path, size=size, is_dir=False)


def _make_dir(name="Show A", path="/remote/Show A") -> RemoteFile:
    return RemoteFile(name=name, path=path, size=0, is_dir=True)


def _walk_result(
    files: list[RemoteFile], io_failures=0, recently_modified_skipped=0
) -> RecursiveListResult:
    return RecursiveListResult(
        files=files, io_failures=io_failures, recently_modified_skipped=recently_modified_skipped
    )


def _make_session() -> MagicMock:
    """Build a mock session with add/commit/begin_nested wired for the happy path."""
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)
    return session


def _make_sftp(
    children_by_path: dict[str, list[RemoteFile]],
    walk_by_path: dict[str, RecursiveListResult | BaseException] | None = None,
    max_workers: int = 8,
) -> MagicMock:
    """Build a mock SFTPService.

    Args:
        children_by_path: remote_path -> list_remote_children() return value.
        walk_by_path: directory path -> list_remote_files_recursive() return
            value, or an exception instance to raise for that path.
        max_workers: value exposed via the max_workers property.
    """
    sftp = MagicMock()
    sftp.max_workers = max_workers

    async def _children(path=None):
        return children_by_path.get(path, [])

    sftp.list_remote_children = AsyncMock(side_effect=_children)

    walk_by_path = walk_by_path or {}

    async def _walk(path=None, pattern="*"):
        outcome = walk_by_path.get(path, _walk_result([]))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    sftp.list_remote_files_recursive = AsyncMock(side_effect=_walk)
    return sftp


def _patch_existing(
    monkeypatch: pytest.MonkeyPatch,
    existing_files: set[str] | None = None,
    existing_dirs: set[str] | None = None,
) -> MagicMock:
    """Patch chunked_existing_paths to answer from fixed existing-files/dirs sets.

    Returns a MagicMock recording every call, so tests can assert call counts
    (e.g. to prove the bulk check replaced the old per-file N+1 SELECT).
    """
    existing_files = existing_files or set()
    existing_dirs = existing_dirs or set()

    async def fake(session, column, paths, chunk_size=1_000):
        target = existing_dirs if column is ScannedDirectory.remote_path else existing_files
        return {p for p in paths if p in target}

    mock = MagicMock(side_effect=fake)
    monkeypatch.setattr("jidou.orchestrators.scan_orchestrator.chunked_existing_paths", mock)
    return mock


# ---------------------------------------------------------------------------
# Top-level files (no directory involved)
# ---------------------------------------------------------------------------


async def test_run_creates_new_top_level_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """New files sitting directly at the configured root are created directly."""
    rf1 = _make_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_file("ep2.mkv", "/remote/ep2.mkv")
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/remote": [rf1, rf2]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 2
    assert result.files_skipped == 0
    assert result.files_found == 2
    assert result.paths_scanned == 1
    assert result.dirs_discovered == 0
    assert session.add.call_count == 2
    session.commit.assert_called_once()
    sftp.list_remote_files_recursive.assert_not_called()


async def test_run_skips_existing_top_level_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file already tracked (any status) is counted as skipped, not recreated."""
    rf = _make_file()
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/remote": [rf]})
    _patch_existing(monkeypatch, existing_files={rf.path})

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_skipped == 1
    assert result.files_created == 0
    session.add.assert_not_called()


async def test_run_dry_run_does_not_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """In dry_run mode, no rows are added and session.commit is not called."""
    rf1 = _make_file("ep1.mkv", "/remote/ep1.mkv")
    rf2 = _make_file("ep2.mkv", "/remote/ep2.mkv")
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/remote": [rf1, rf2]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run(dry_run=True)

    assert result.files_created == 2
    session.add.assert_not_called()
    session.commit.assert_not_called()


async def test_run_continues_on_shallow_listing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If shallow listing fails for one path, other paths are still processed."""
    rf = _make_file()
    session = _make_session()
    sftp = MagicMock()
    sftp.max_workers = 8
    sftp.list_remote_children = AsyncMock(side_effect=[Exception("connection error"), [rf]])
    sftp.list_remote_files_recursive = AsyncMock(return_value=_walk_result([]))
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/bad/path", "/good/path"])
    result = await orch.run()

    assert result.paths_scanned == 2
    assert result.files_created == 1


async def test_run_scans_multiple_remote_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each configured remote path is scanned independently."""
    rf1 = _make_file("ep1.mkv", "/path1/ep1.mkv")
    rf2 = _make_file("ep2.mkv", "/path2/ep2.mkv")
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/path1": [rf1], "/path2": [rf2]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/path1", "/path2"])
    result = await orch.run()

    assert result.paths_scanned == 2
    assert result.files_found == 2
    assert result.files_created == 2
    assert sftp.list_remote_children.call_count == 2


async def test_run_skips_duplicate_file_on_constraint_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unique constraint violation (pgcode 23505) skips the file without failing."""
    from sqlalchemy.exc import IntegrityError

    rf = _make_file()
    session = _make_session()

    orig = Exception("unique constraint violated")
    orig.pgcode = "23505"  # type: ignore[attr-defined]
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.side_effect = IntegrityError("stmt", {}, orig)
    session.begin_nested = MagicMock(return_value=nested_ctx)

    sftp = _make_sftp(children_by_path={"/remote": [rf]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 0
    assert result.files_skipped == 1
    session.commit.assert_called_once()


async def test_run_reraises_non_unique_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-unique integrity errors (FK violation) propagate out of run()."""
    from sqlalchemy.exc import IntegrityError

    rf = _make_file()
    session = _make_session()

    orig = Exception("foreign key constraint violated")
    orig.pgcode = "23503"  # type: ignore[attr-defined]
    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.side_effect = IntegrityError("stmt", {}, orig)
    session.begin_nested = MagicMock(return_value=nested_ctx)

    sftp = _make_sftp(children_by_path={"/remote": [rf]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    with pytest.raises(IntegrityError):
        await orch.run()


async def test_on_progress_called_per_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """on_progress callback is called once per remote path with correct index."""
    session = _make_session()
    sftp = _make_sftp(children_by_path={})
    _patch_existing(monkeypatch)

    on_progress = AsyncMock()
    orch = ScanOrchestrator(session, sftp, ["/path/a", "/path/b"])
    await orch.run(on_progress=on_progress)

    assert on_progress.call_count == 2
    calls = on_progress.call_args_list
    assert calls[0].args == (1, 2, "Scanning /path/a")
    assert calls[1].args == (2, 2, "Scanning /path/b")


async def test_created_files_have_null_show_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """DISCOVERED records must be created with show_id=None (global scan)."""
    rf = _make_file("ep.mkv", "/remote/ep.mkv")
    added_files: list[object] = []
    session = _make_session()
    session.add = MagicMock(side_effect=lambda f: added_files.append(f))
    sftp = _make_sftp(children_by_path={"/remote": [rf]})
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    await orch.run()

    assert len(added_files) == 1
    added = added_files[0]
    assert isinstance(added, DownloadedFile)
    assert added.show_id is None
    assert added.status.value == "discovered"


async def test_bulk_existence_check_not_called_once_per_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existence checking is batched, not one query per file (the fixed N+1)."""
    files = [_make_file(f"ep{i}.mkv", f"/remote/ep{i}.mkv") for i in range(50)]
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/remote": files})
    mock_existing = _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 50
    # One bulk call for top-level files (+ one for top-level dirs, even if empty)
    assert mock_existing.call_count <= 2


# ---------------------------------------------------------------------------
# Directories: lazy deep-walk + ScannedDirectory marking
# ---------------------------------------------------------------------------


async def test_new_directory_triggers_deep_walk_and_creates_files_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new top-level directory is deep-walked, its files created, and marked known."""
    show_dir = _make_dir("Show A", "/remote/Show A")
    ep = _make_file("ep01.mkv", "/remote/Show A/Season 01/ep01.mkv")

    session = _make_session()
    added: list[object] = []
    session.add = MagicMock(side_effect=lambda o: added.append(o))
    sftp = _make_sftp(
        children_by_path={"/remote": [show_dir]},
        walk_by_path={"/remote/Show A": _walk_result([ep])},
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.dirs_discovered == 1
    assert result.files_created == 1
    sftp.list_remote_files_recursive.assert_called_once_with("/remote/Show A")
    marker_rows = [o for o in added if isinstance(o, ScannedDirectory)]
    assert len(marker_rows) == 1
    assert marker_rows[0].remote_path == "/remote/Show A"


async def test_known_directory_is_never_deep_walked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A directory already marked known is skipped entirely — no SFTP round trip.

    This is the core regression-proof of the redesign: the whole point is
    that a known directory costs zero SFTP round trips on every future scan.
    """
    show_dir = _make_dir("Show A", "/remote/Show A")
    session = _make_session()
    sftp = _make_sftp(children_by_path={"/remote": [show_dir]})
    _patch_existing(monkeypatch, existing_dirs={"/remote/Show A"})

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.dirs_discovered == 0
    sftp.list_remote_files_recursive.assert_not_called()


async def test_directory_with_io_failure_gets_files_but_no_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partially-failed walk still records the files it did find, but is not marked known."""
    show_dir = _make_dir("Show A", "/remote/Show A")
    ep = _make_file("ep01.mkv", "/remote/Show A/Season 01/ep01.mkv")

    session = _make_session()
    added: list[object] = []
    session.add = MagicMock(side_effect=lambda o: added.append(o))
    sftp = _make_sftp(
        children_by_path={"/remote": [show_dir]},
        walk_by_path={"/remote/Show A": _walk_result([ep], io_failures=1)},
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 1
    assert not any(isinstance(o, ScannedDirectory) for o in added)


async def test_directory_with_recently_modified_skip_gets_no_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directory with an in-flight upload is not marked known (would miss the file)."""
    show_dir = _make_dir("Show A", "/remote/Show A")
    ep = _make_file("ep01.mkv", "/remote/Show A/Season 01/ep01.mkv")

    session = _make_session()
    added: list[object] = []
    session.add = MagicMock(side_effect=lambda o: added.append(o))
    sftp = _make_sftp(
        children_by_path={"/remote": [show_dir]},
        walk_by_path={"/remote/Show A": _walk_result([ep], recently_modified_skipped=1)},
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    await orch.run()

    assert not any(isinstance(o, ScannedDirectory) for o in added)


async def test_multiple_new_directories_all_get_walked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Several new directories in one scan are all deep-walked (bounded concurrency)."""
    dirs = [_make_dir(f"Show {c}", f"/remote/Show {c}") for c in "ABC"]
    session = _make_session()
    sftp = _make_sftp(
        children_by_path={"/remote": dirs},
        walk_by_path={d.path: _walk_result([]) for d in dirs},
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.dirs_discovered == 3
    assert sftp.list_remote_files_recursive.call_count == 3


async def test_one_directory_walk_exception_does_not_affect_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception walking one new directory doesn't create its marker or affect siblings."""
    good = _make_dir("Show Good", "/remote/Show Good")
    bad = _make_dir("Show Bad", "/remote/Show Bad")
    ep = _make_file("ep01.mkv", "/remote/Show Good/ep01.mkv")

    session = _make_session()
    added: list[object] = []
    session.add = MagicMock(side_effect=lambda o: added.append(o))
    sftp = _make_sftp(
        children_by_path={"/remote": [good, bad]},
        walk_by_path={
            "/remote/Show Good": _walk_result([ep]),
            "/remote/Show Bad": RuntimeError("connection reset"),
        },
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    result = await orch.run()

    assert result.files_created == 1
    markers = [o for o in added if isinstance(o, ScannedDirectory)]
    assert [m.remote_path for m in markers] == ["/remote/Show Good"]


async def test_dry_run_skips_directory_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run must not insert a ScannedDirectory row either."""
    show_dir = _make_dir("Show A", "/remote/Show A")
    session = _make_session()
    sftp = _make_sftp(
        children_by_path={"/remote": [show_dir]},
        walk_by_path={"/remote/Show A": _walk_result([])},
    )
    _patch_existing(monkeypatch)

    orch = ScanOrchestrator(session, sftp, ["/remote"])
    await orch.run(dry_run=True)

    session.add.assert_not_called()

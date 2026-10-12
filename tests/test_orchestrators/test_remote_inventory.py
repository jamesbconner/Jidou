"""Tests for the shared scan/seed SFTP discovery helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.orchestrators._remote_inventory import list_roots, walk_directories
from jidou.services.sftp_service import RecursiveListResult, RemoteFile


def _file(path: str) -> RemoteFile:
    return RemoteFile(name=path.rsplit("/", 1)[-1], path=path, size=1, is_dir=False)


def _dir(path: str) -> RemoteFile:
    return RemoteFile(name=path.rsplit("/", 1)[-1], path=path, size=0, is_dir=True)


async def test_list_roots_splits_files_and_dirs_and_counts_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Files and directories are separated in order; a failing root is counted and logged."""
    children = {"/a": [_file("/a/1.mkv"), _dir("/a/D")], "/c": [_file("/c/2.mkv")]}

    async def list_children(path: str | None = None) -> list[RemoteFile]:
        if path == "/b":
            raise OSError("down")
        return children[path or ""]

    sftp = MagicMock()
    sftp.list_remote_children = AsyncMock(side_effect=list_children)
    on_error = AsyncMock()

    listing = await list_roots(sftp, ["/a", "/b", "/c"], on_error=on_error)

    assert [f.path for f in listing.files] == ["/a/1.mkv", "/c/2.mkv"]
    assert [d.path for d in listing.dirs] == ["/a/D"]
    assert listing.failed_roots == 1
    assert on_error.await_count == 1
    assert on_error.await_args.args[0] == "/b"
    assert isinstance(on_error.await_args.args[1], OSError)
    assert "Failed to list remote path /b; skipping" in caplog.text


async def test_list_roots_calls_before_each_before_listing() -> None:
    """before_each runs with (index, total, root) immediately before each listing."""
    order: list[str] = []

    async def list_children(path: str | None = None) -> list[RemoteFile]:
        order.append(f"list {path}")
        if path == "/b":
            raise OSError("down")
        return []

    async def before_each(idx: int, total: int, root: str) -> None:
        order.append(f"before {idx}/{total} {root}")

    async def on_error(root: str, exc: Exception) -> None:
        order.append(f"error {root}")

    sftp = MagicMock()
    sftp.list_remote_children = AsyncMock(side_effect=list_children)

    await list_roots(sftp, ["/a", "/b"], before_each=before_each, on_error=on_error)

    assert order == [
        "before 1/2 /a",
        "list /a",
        "before 2/2 /b",
        "list /b",
        "error /b",
    ]


async def test_list_roots_without_hooks_and_no_roots() -> None:
    """No roots means no SFTP call and an empty listing."""
    sftp = MagicMock()
    sftp.list_remote_children = AsyncMock()

    listing = await list_roots(sftp, [])

    assert (listing.files, listing.dirs, listing.failed_roots) == ([], [], 0)
    sftp.list_remote_children.assert_not_called()


async def test_walk_directories_empty_makes_no_sftp_call() -> None:
    """An empty directory list returns an empty outcome without touching SFTP."""
    sftp = MagicMock()
    sftp.list_remote_files_recursive_batch = AsyncMock()

    outcome = await walk_directories(sftp, [])

    assert outcome.walked == []
    assert outcome.failures == []
    sftp.list_remote_files_recursive_batch.assert_not_called()


async def test_walk_directories_splits_results_from_failures_in_order() -> None:
    """Successful walks and raised exceptions are separated, each keeping batch order."""
    ok1, ok2 = RecursiveListResult(files=[_file("/a/1.mkv")]), RecursiveListResult()
    boom = RuntimeError("boom")
    sftp = MagicMock()
    sftp.list_remote_files_recursive_batch = AsyncMock(
        return_value=[("/a", ok1), ("/b", boom), ("/c", ok2)]
    )

    outcome = await walk_directories(sftp, ["/a", "/b", "/c"])

    sftp.list_remote_files_recursive_batch.assert_awaited_once_with(["/a", "/b", "/c"])
    assert outcome.walked == [("/a", ok1), ("/c", ok2)]
    assert outcome.failures == [("/b", boom)]

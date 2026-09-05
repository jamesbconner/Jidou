"""Tests for jidou.services.file_reconciliation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.services.file_reconciliation import reconcile_local_file_existence
from jidou.services.path_transport import encode_path_bytes


def _make_row(
    *, local_path: str | None, status: FileStatus, episode_id: int | None = None
) -> MagicMock:
    row = MagicMock()
    row.local_path = local_path
    row.status = status
    row.episode_id = episode_id
    return row


def _make_session(rows: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_marks_row_missing_when_local_path_gone(tmp_path) -> None:
    """A settled-status row whose local_path no longer exists flips to MISSING."""
    row = _make_row(local_path=str(tmp_path / "gone.mkv"), status=FileStatus.UNMATCHED)
    session = _make_session([row])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome.marked_missing == 1
    assert outcome.restored == 0
    assert row.status == FileStatus.MISSING
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_leaves_row_alone_when_file_present(tmp_path) -> None:
    """A row whose file still exists on disk is untouched."""
    real_file = tmp_path / "present.mkv"
    real_file.write_text("data")
    row = _make_row(local_path=str(real_file), status=FileStatus.MATCHED, episode_id=5)
    session = _make_session([row])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome.marked_missing == 0
    assert outcome.restored == 0
    assert row.status == FileStatus.MATCHED
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_restores_matched_row_when_file_reappears(tmp_path) -> None:
    """A MISSING row with an episode_id reverts to MATCHED once its file is back."""
    real_file = tmp_path / "back.mkv"
    real_file.write_text("data")
    row = _make_row(local_path=str(real_file), status=FileStatus.MISSING, episode_id=7)
    session = _make_session([row])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome.marked_missing == 0
    assert outcome.restored == 1
    assert row.status == FileStatus.MATCHED


@pytest.mark.asyncio
async def test_restores_unmatched_row_when_file_reappears_without_episode(tmp_path) -> None:
    """A MISSING row with no episode_id reverts to UNMATCHED once its file is back."""
    real_file = tmp_path / "back.mkv"
    real_file.write_text("data")
    row = _make_row(local_path=str(real_file), status=FileStatus.MISSING, episode_id=None)
    session = _make_session([row])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome.restored == 1
    assert row.status == FileStatus.UNMATCHED


@pytest.mark.asyncio
async def test_no_rows_is_a_no_op() -> None:
    """No candidate rows for the show: no queries beyond the initial select, no commit."""
    session = _make_session([])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome == outcome.__class__(marked_missing=0, restored=0)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_excludes_synthetic_import_rows() -> None:
    """The select statement filters out synthetic-import rows at the SQL level.

    Regression test (Bugbot finding on PR #568): bulk path-import and "Enter
    file path" both record a DownloadedFile keyed by a synthetic-import://
    remote_path, sometimes using a host/catalog path (e.g. a Windows drive
    letter) that can never resolve inside this container. Reconciliation
    must never treat those as verifiable, or it would flag perfectly valid
    tracked files as missing.
    """
    session = _make_session([])

    await reconcile_local_file_existence(session, show_id=1)

    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "synthetic-import" in compiled


@pytest.mark.asyncio
async def test_encoded_local_path_is_decoded_before_checking_existence(tmp_path) -> None:
    """A percent-encoded local_path pointing at a real file is not flagged missing.

    Regression test (Bugbot finding on PR #568): local_path is stored in its
    JSON/DB-safe encoded transport form (see path_transport.py), not a
    directly usable filesystem path.
    """
    real_file = tmp_path / "100% Real.mkv"
    real_file.write_text("data")
    encoded_path = encode_path_bytes(str(real_file))
    assert "%25" in encoded_path  # sanity: the literal '%' really is escaped

    row = _make_row(local_path=encoded_path, status=FileStatus.UNMATCHED)
    session = _make_session([row])

    outcome = await reconcile_local_file_existence(session, show_id=1)

    assert outcome.marked_missing == 0
    assert row.status == FileStatus.UNMATCHED

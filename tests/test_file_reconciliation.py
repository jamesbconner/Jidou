"""Tests for jidou.services.file_reconciliation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.models.downloaded_file import FileStatus
from jidou.services.file_reconciliation import reconcile_local_file_existence


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

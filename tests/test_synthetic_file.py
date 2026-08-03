"""Tests for jidou.services.synthetic_file."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.path_transport import encode_path_bytes
from jidou.services.synthetic_file import create_synthetic_import_file


def _make_session(existing: MagicMock | None = None) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=result)

    nested_ctx = AsyncMock()
    nested_ctx.__aenter__.return_value = None
    nested_ctx.__aexit__.return_value = False
    session.begin_nested = MagicMock(return_value=nested_ctx)
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_original_filename_is_decoded_for_display() -> None:
    """original_filename stores the readable form, not the byte-exact encoding.

    Regression test: original_filename is display-only (never echoed back
    for a lookup, unlike local_path/remote_path), so it should show a
    human-readable name — not the raw %-encoded transport form.
    """
    session = _make_session()
    raw_path = encode_path_bytes("/media/Show/The Fianc\udce9.S01E01.mkv")
    assert "%E9" in raw_path  # sanity: the non-UTF-8 byte really is escaped

    record = await create_synthetic_import_file(
        session, show_id=1, episode_id=10, raw_path=raw_path
    )

    assert record is not None
    assert record.original_filename == "The Fiancé.S01E01.mkv"
    # local_path stays byte-exact — it's what a future real filesystem
    # access would need to decode back to the exact original bytes.
    assert record.local_path == raw_path


@pytest.mark.asyncio
async def test_original_filename_normal_path_unaffected() -> None:
    """A path with no encoding needed round-trips through unchanged."""
    session = _make_session()
    raw_path = "/media/Show/Episode.S01E01.mkv"

    record = await create_synthetic_import_file(
        session, show_id=1, episode_id=10, raw_path=raw_path
    )

    assert record is not None
    assert record.original_filename == "Episode.S01E01.mkv"


@pytest.mark.asyncio
async def test_episode_id_none_for_movie_file() -> None:
    """A movie file is linked to the show alone, with no episode_id."""
    session = _make_session()

    record = await create_synthetic_import_file(
        session, show_id=1, episode_id=None, raw_path="/media/Movies/Movie/Movie.mkv"
    )

    assert record is not None
    assert record.show_id == 1
    assert record.episode_id is None
    assert record.parsed_season is None
    assert record.parsed_episode is None


@pytest.mark.asyncio
async def test_stores_parsed_season_and_episode_when_provided() -> None:
    """parsed_season/parsed_episode round-trip onto the created record.

    Regression test: without these, ShowRematchOrchestrator's Phase 3
    orphan-relink pass can never find this row after a future rematch (its
    query requires both to be non-null), silently leaving the file
    unlinked forever. See issue #424.
    """
    session = _make_session()

    record = await create_synthetic_import_file(
        session,
        show_id=1,
        episode_id=10,
        raw_path="/media/Show/ep.mkv",
        parsed_season=3,
        parsed_episode=7,
    )

    assert record is not None
    assert record.parsed_season == 3
    assert record.parsed_episode == 7


@pytest.mark.asyncio
async def test_returns_existing_record_without_creating_duplicate() -> None:
    """An existing synthetic row for the same path is returned as-is."""
    existing = MagicMock()
    session = _make_session(existing=existing)

    record = await create_synthetic_import_file(
        session, show_id=1, episode_id=10, raw_path="/media/Show/ep.mkv"
    )

    assert record is existing
    session.add.assert_not_called()

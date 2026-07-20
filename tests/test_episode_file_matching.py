"""Tests for services/episode_file_matching.py — match_entry_to_episode().

Extracted from PathImportOrchestrator._find_episode (see test_path_import.py
for orchestrator-level behavior tests that patch this function as a
collaborator) — these test the matching lookup chain itself in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jidou.services.episode_file_matching import match_entry_to_episode
from jidou.services.path_parser import ParsedPathEntry


def _make_episode(*, id: int, show_id: int, season: int, episode: int) -> MagicMock:
    ep = MagicMock()
    ep.id = id
    ep.show_id = show_id
    ep.season_number = season
    ep.episode_number = episode
    ep.absolute_episode_number = None
    ep.file_tracked = False
    return ep


# ---------------------------------------------------------------------------
# LLM filename-parse fallback (unit tests for llm_parse_episode itself live
# in tests/test_episode_match_llm.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uses_llm_when_episode_none() -> None:
    """When regex gives episode=None, the LLM parses the filename and hits the DB."""
    episode = _make_episode(id=10, show_id=1, season=6, episode=11)

    session = AsyncMock()
    ep_result = MagicMock()
    ep_result.scalar_one_or_none.return_value = episode
    session.execute.return_value = ep_result

    mock_response = MagicMock()
    mock_response.content = '{"season": 6, "episode": 11}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Criminal Minds\Season 6\Episode 11 - 25 to Life.avi",
        show_dir="Criminal Minds",
        show_root=r"Z:\tv\Criminal Minds",
        season=6,
        episode=None,  # regex could not parse
        is_absolute=False,
    )

    ep, season, ep_num = await match_entry_to_episode(
        session, llm, show_id=1, show_title="Criminal Minds", entry=entry
    )
    assert ep is episode
    assert season == 6
    assert ep_num == 11
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_returns_none_when_llm_also_fails() -> None:
    """If episode is None and LLM also returns None, no episode is matched."""
    session = AsyncMock()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=MagicMock(content='{"season": null, "episode": null}'))

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\SomeShow\Season 1\SomeShow.Extras.mkv",
        show_dir="SomeShow",
        show_root=r"Z:\tv\SomeShow",
        season=1,
        episode=None,
        is_absolute=False,
    )

    ep, season, ep_num = await match_entry_to_episode(
        session, llm, show_id=1, show_title="SomeShow", entry=entry
    )
    assert ep is None
    assert season == 1
    assert ep_num is None


# ---------------------------------------------------------------------------
# Additional lookup branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_season_gt_1_miss_tries_absolute_lookup_then_llm() -> None:
    """A season>1 S/E miss tries absolute-number lookups before the LLM."""
    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=3,
        episode=99,
        is_absolute=False,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm_match:
        ep, season, ep_num = await match_entry_to_episode(
            session, AsyncMock(), show_id=1, show_title="Show", entry=entry
        )

    assert ep is None
    assert season == 3
    assert ep_num == 99
    mock_llm_match.assert_called_once()
    # S/E lookup + absolute_episode_number lookup + season-1 fallback lookup = 3.
    # (No episode_group_map was passed, so the declared-season remap step is a
    # free no-op that issues no query of its own.)
    assert session.execute.call_count == 3


@pytest.mark.asyncio
async def test_season_gt_1_miss_resolves_via_absolute_lookup() -> None:
    """A season>1 S/E miss that resolves via absolute lookup never reaches the LLM."""
    matched_episode = _make_episode(id=9, show_id=1, season=1, episode=99)

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[miss, hit])

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=3,
        episode=99,
        is_absolute=False,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm:
        ep, season, ep_num = await match_entry_to_episode(
            session, AsyncMock(), show_id=1, show_title="Show", entry=entry
        )

    assert ep is matched_episode
    assert season == 3
    assert ep_num == 99
    mock_llm.assert_not_called()
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_season_gt_1_miss_uses_absolute_candidate_over_bare_episode() -> None:
    """An ambiguous compact-code guess (e.g. "212" -> S02E12) uses the raw
    joined number for the absolute lookup, not the split episode component —
    this is exactly the "One Piece 212" / "Bleach 260" scenario.
    """
    matched_episode = _make_episode(id=9, show_id=1, season=1, episode=212)

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = matched_episode

    bound_absolute_numbers: list[int] = []

    async def capture_execute(stmt: object) -> MagicMock:
        params = stmt.compile().params  # type: ignore[attr-defined]
        if "absolute_episode_number_1" in params:
            bound_absolute_numbers.append(params["absolute_episode_number_1"])
            return hit
        return miss

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=capture_execute)

    # Compact-code guessed S02E12 from "212", but absolute_candidate=212 is
    # the raw number — that's what must be used for the absolute lookup.
    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\One Piece\One Piece 212.mkv",
        show_dir="One Piece",
        show_root=r"Z:\anime tv\One Piece",
        season=2,
        episode=12,
        is_absolute=False,
        absolute_candidate=212,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm:
        ep, _season, _ep_num = await match_entry_to_episode(
            session, AsyncMock(), show_id=1, show_title="One Piece", entry=entry
        )

    assert ep is matched_episode
    mock_llm.assert_not_called()
    assert bound_absolute_numbers == [212]


@pytest.mark.asyncio
async def test_absolute_number_column_hit() -> None:
    """No season known; absolute_episode_number column match is used directly."""
    episode = _make_episode(id=5, show_id=1, season=1, episode=146)
    episode.absolute_episode_number = 146

    session = AsyncMock()
    abs_hit = MagicMock()
    abs_hit.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=abs_hit)

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\HxH\HxH - 146.mkv",
        show_dir="HxH",
        show_root=r"Z:\anime tv\HxH",
        season=None,
        episode=146,
        is_absolute=True,
    )

    ep, season, ep_num = await match_entry_to_episode(
        session, AsyncMock(), show_id=1, show_title="HxH", entry=entry
    )
    assert ep is episode
    assert season is None
    assert ep_num == 146
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_falls_through_to_llm_match_when_all_lookups_fail() -> None:
    """When the absolute-number and Season-1 fallback lookups both miss, falls back to the LLM."""
    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\HxH\HxH - 999.mkv",
        show_dir="HxH",
        show_root=r"Z:\anime tv\HxH",
        season=None,
        episode=999,
        is_absolute=True,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm_match:
        ep, season, ep_num = await match_entry_to_episode(
            session, AsyncMock(), show_id=1, show_title="HxH", entry=entry
        )

    assert ep is None
    assert season is None
    assert ep_num == 999
    mock_llm_match.assert_called_once()
    # absolute_episode_number lookup + Season-1 fallback lookup = 2 execute
    # calls before giving up.
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_season_gt_1_miss_resolves_via_episode_group_remap() -> None:
    """A season>1 S/E miss resolves through episode_group_map before absolute/LLM.

    This is the Frieren regression case: a fansub's "Season 02" folder (S2E01)
    doesn't exist in TMDB's real single-season structure, but the show's
    type-6 episode_group_map says declared season 2 position 1 is really
    (season=1, episode=4) -- the remap must resolve it without ever falling
    through to the absolute-number column or the LLM.
    """
    from jidou.services.episode_group_mapping import to_storage_map

    remapped_episode = _make_episode(id=9, show_id=1, season=1, episode=4)

    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = remapped_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[miss, hit])

    episode_group_map = to_storage_map({6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]}})

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\Frieren\Season 02\Frieren.S02E01.mkv",
        show_dir="Frieren",
        show_root=r"Z:\anime tv\Frieren",
        season=2,
        episode=1,
        is_absolute=False,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm:
        ep, season, ep_num = await match_entry_to_episode(
            session,
            AsyncMock(),
            show_id=1,
            show_title="Frieren",
            entry=entry,
            episode_group_map=episode_group_map,
        )

    assert ep is remapped_episode
    assert season == 1
    assert ep_num == 4
    mock_llm.assert_not_called()
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_season_gt_1_miss_remap_miss_falls_through_to_absolute() -> None:
    """When the remapped (season, episode) pair also misses the DB, falls through
    to the absolute-number lookup rather than giving up immediately."""
    from jidou.services.episode_group_mapping import to_storage_map

    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    episode_group_map = to_storage_map({6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]}})

    entry = ParsedPathEntry(
        raw_path=r"Z:\anime tv\Frieren\Season 02\Frieren.S02E01.mkv",
        show_dir="Frieren",
        show_root=r"Z:\anime tv\Frieren",
        season=2,
        episode=1,
        is_absolute=False,
    )

    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, None, None)),
    ) as mock_llm:
        ep, _season, _ep_num = await match_entry_to_episode(
            session,
            AsyncMock(),
            show_id=1,
            show_title="Frieren",
            entry=entry,
            episode_group_map=episode_group_map,
        )

    assert ep is None
    mock_llm.assert_called_once()
    # S/E miss + remapped S/E miss + absolute lookup + Season-1 fallback = 4.
    assert session.execute.call_count == 4


@pytest.mark.asyncio
async def test_llm_fills_in_season_when_originally_none() -> None:
    """When both season and episode are unknown, the LLM's season is adopted too."""
    episode = _make_episode(id=8, show_id=1, season=4, episode=12)

    mock_response = MagicMock()
    mock_response.content = '{"season": 4, "episode": 12}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = episode
    session.execute = AsyncMock(return_value=hit)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\some_unusual_filename.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,  # regex could not determine season
        episode=None,  # regex could not determine episode either
        is_absolute=True,
    )

    ep, season, ep_num = await match_entry_to_episode(
        session, llm, show_id=1, show_title="Show", entry=entry
    )
    assert ep is episode
    assert season == 4
    assert ep_num == 12
    # Confirms the S/E lookup ran with the LLM-supplied season (4), not a miss.
    assert session.execute.call_count == 1


# ---------------------------------------------------------------------------
# LLM fallback diagnostics — outcomes reflected in the returned season/episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_surfaces_llm_season_when_episode_still_none() -> None:
    """Bugbot-caught regression: llm_parse_episode can resolve a season
    without an episode. That season must not be silently discarded just
    because the overall attempt still failed.
    """
    mock_response = MagicMock()
    mock_response.content = '{"season": 2, "episode": null}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Show Extras.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,  # regex found no season either
        episode=None,
        is_absolute=True,
    )

    ep, season, episode_num = await match_entry_to_episode(
        AsyncMock(), llm, show_id=1, show_title="Show", entry=entry
    )

    assert ep is None
    assert season == 2  # LLM's season must be surfaced, not discarded
    assert episode_num is None


@pytest.mark.asyncio
async def test_uses_llm_match_season_episode_over_stale_locals() -> None:
    """Bugbot-caught regression: when llm_match_episode proposes a season/episode
    that has no matching DB row, the result must reflect what llm_match_episode
    actually proposed, not the season/episode from before it ran, so the
    "No match" event agrees with the separate "LLM episode-list match proposed
    ..." warn event emitted by the caller.
    """
    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=miss)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Season 3\Show.S03E99.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=3,
        episode=99,
        is_absolute=False,
    )

    # llm_match_episode proposed S05E10, distinct from the pre-existing S03E99.
    with patch(
        "jidou.services.episode_file_matching.llm_match_episode",
        AsyncMock(return_value=(None, 5, 10)),
    ):
        ep, season, episode_num = await match_entry_to_episode(
            session, AsyncMock(), show_id=1, show_title="Show", entry=entry
        )

    assert ep is None
    assert season == 5
    assert episode_num == 10

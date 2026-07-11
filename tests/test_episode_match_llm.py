"""Tests for jidou.services.episode_match_llm."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.episode_match_llm import (
    llm_match_episode,
    llm_parse_episode,
    llm_pick_candidate,
)
from jidou.services.path_parser import ParsedPathEntry


def _make_ep_row(season: int, episode: int, name: str = "Episode") -> MagicMock:
    """Build a mock Episode row for the LLM episode-list prompt."""
    ep = MagicMock()
    ep.season_number = season
    ep.episode_number = episode
    ep.name = name
    return ep


def _make_episode(ep_id: int, show_id: int, season: int, episode: int) -> MagicMock:
    ep = MagicMock()
    ep.id = ep_id
    ep.show_id = show_id
    ep.season_number = season
    ep.episode_number = episode
    return ep


def _event_capture() -> tuple[list[tuple[str, str, object]], object]:
    events: list[tuple[str, str, object]] = []

    async def capture(level: str, msg: str, ctx: object = None) -> None:
        events.append((level, msg, ctx))

    return events, capture


# ---------------------------------------------------------------------------
# llm_parse_episode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_parse_episode_unavailable_returns_none() -> None:
    """When LLM is not configured, llm_parse_episode returns (None, None)."""
    season, episode = await llm_parse_episode(None, "criminal.minds.201.hdtv-lol.avi")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_valid_json() -> None:
    """LLM returning valid JSON yields the correct (season, episode) pair."""
    mock_response = MagicMock()
    mock_response.content = '{"season": 2, "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "criminal.minds.201.hdtv-lol.avi")
    assert season == 2
    assert episode == 1


@pytest.mark.asyncio
async def test_llm_parse_episode_null_season() -> None:
    """LLM may return season=null when only episode can be determined."""
    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": 7}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "Show.Episode.07.mkv")
    assert season is None
    assert episode == 7


@pytest.mark.asyncio
async def test_llm_parse_episode_invalid_json_returns_none() -> None:
    """Malformed LLM response is handled gracefully; (None, None) is returned."""
    mock_response = MagicMock()
    mock_response.content = "I cannot determine the episode number."
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "some.unusual.filename.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_non_dict_json_returns_none() -> None:
    """Bare JSON null (valid JSON but not a dict) must not crash with AttributeError."""
    mock_response = MagicMock()
    mock_response.content = "null"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "some.unusual.filename.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_sends_known_season_hint() -> None:
    """known_season is included in the prompt when supplied."""
    mock_response = MagicMock()
    mock_response.content = '{"season": 6, "episode": 11}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    await llm_parse_episode(llm, "Episode 11 - 25 to Life.avi", known_season=6)

    call_kwargs = llm.complete.call_args
    prompt_text = call_kwargs.kwargs.get("prompt") or call_kwargs.args[0]
    assert "Known season from directory: 6" in prompt_text


@pytest.mark.asyncio
async def test_llm_parse_episode_system_prompt_covers_bare_numbers_and_non_episode_assets() -> None:
    """Regression: the episode-parse prompt was trimmed down to 4 lines with
    no guidance at all, losing coverage for bare trailing numbers and
    non-episode bonus content (NCED/NCOP/OVA/etc.) that an earlier, more
    detailed prompt used to handle correctly.
    """
    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": 9}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    await llm_parse_episode(llm, "Show 09.mkv")

    system_text = llm.complete.call_args.kwargs["system"]
    assert "bare trailing number" in system_text.lower()
    assert "never the season" in system_text.lower()
    assert "ncop" in system_text.lower()
    assert "never infer season" in system_text.lower()


@pytest.mark.asyncio
async def test_llm_parse_episode_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    mock_response = MagicMock()
    mock_response.content = '```json\n{"season": 3, "episode": 5}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "Show.S03E05.mkv")
    assert season == 3
    assert episode == 5


@pytest.mark.asyncio
async def test_llm_parse_episode_complete_raises_returns_none_none() -> None:
    """An exception from llm.complete() is caught; (None, None) is returned."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM provider down"))

    season, episode = await llm_parse_episode(llm, "some.file.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_response_none_returns_none_none() -> None:
    """llm.complete() returning None (provider unavailable) yields (None, None)."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    season, episode = await llm_parse_episode(llm, "some.file.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_non_integer_values_return_none_none() -> None:
    """Non-integer season/episode values in the LLM's JSON are handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = '{"season": "two", "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    season, episode = await llm_parse_episode(llm, "some.file.mkv")
    assert season is None
    assert episode is None


@pytest.mark.asyncio
async def test_llm_parse_episode_exception_is_emitted() -> None:
    """A failure is surfaced via on_event, not just the Python logger."""
    events, capture = _event_capture()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("connection refused"))

    result = await llm_parse_episode(llm, "Bamboo Blade 20.mkv", on_event=capture)

    assert result == (None, None)
    failures = [(lvl, msg) for lvl, msg, _ in events if "episode-parse failed" in msg]
    assert len(failures) == 1
    assert failures[0][0] == "warn"
    assert "connection refused" in failures[0][1]


@pytest.mark.asyncio
async def test_llm_parse_episode_success_is_emitted() -> None:
    """A successful parse is surfaced via on_event with structured context."""
    events, capture = _event_capture()
    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": 20}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_parse_episode(llm, "Bamboo Blade 20.mkv", on_event=capture)

    assert result == (None, 20)
    successes = [(lvl, msg, ctx) for lvl, msg, ctx in events if "LLM episode-parse:" in msg]
    assert len(successes) == 1
    assert successes[0][0] == "info"
    assert successes[0][2] == {
        "filename": "Bamboo Blade 20.mkv",
        "season": None,
        "episode": 20,
    }


# ---------------------------------------------------------------------------
# llm_pick_candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_pick_candidate_complete_raises_returns_none() -> None:
    """An exception from llm.complete() is caught; None is returned."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_response_none_returns_none() -> None:
    """llm.complete() returning None yields None."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_invalid_json_returns_none() -> None:
    """Malformed JSON from the LLM is handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = "I'm not sure which one matches."
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_non_integer_match_returns_none() -> None:
    """A non-integer 'match' value in the LLM's JSON is handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = '{"match": "one"}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_out_of_range_index_returns_none() -> None:
    """An out-of-range candidate index from the LLM is handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = '{"match": 99}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    mock_response = MagicMock()
    mock_response.content = '```json\n{"match": 1}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result == {"name": "Show", "id": 1}


@pytest.mark.asyncio
async def test_llm_pick_candidate_null_match_returns_none() -> None:
    """A valid JSON response with match=null means the LLM found no confident match."""
    mock_response = MagicMock()
    mock_response.content = '{"match": null}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}])
    assert result is None


@pytest.mark.asyncio
async def test_llm_pick_candidate_exception_is_emitted() -> None:
    """A failure is surfaced via on_event, not just the Python logger."""
    events, capture = _event_capture()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("bad gateway"))

    result = await llm_pick_candidate(llm, "Show", [{"name": "Show", "id": 1}], on_event=capture)

    assert result is None
    failures = [(lvl, msg) for lvl, msg, _ in events if "show-match failed" in msg]
    assert len(failures) == 1
    assert failures[0][0] == "warn"
    assert "bad gateway" in failures[0][1]


# ---------------------------------------------------------------------------
# llm_match_episode
# ---------------------------------------------------------------------------


def _make_entry(episode: int | None = 1, season: int | None = None) -> ParsedPathEntry:
    return ParsedPathEntry(
        raw_path=r"Z:\tv\Show\ep.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=season,
        episode=episode,
        is_absolute=True,
    )


@pytest.mark.asyncio
async def test_llm_match_unavailable_returns_none() -> None:
    """When no LLM is configured, llm_match_episode returns None immediately."""
    session = AsyncMock()

    ep, season, episode_num = await llm_match_episode(
        session, None, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_llm_match_no_episodes_returns_none() -> None:
    """When the show has no episode rows at all, returns None without calling the LLM."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock()

    session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_llm_match_complete_raises_returns_none() -> None:
    """An exception from llm.complete() is caught; None is returned."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_response_none_returns_none() -> None:
    """llm.complete() returning None yields None."""
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=None)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_invalid_json_returns_none() -> None:
    """Malformed JSON from the LLM is handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = "not json at all"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_non_dict_json_returns_none() -> None:
    """Valid JSON that isn't a dict (e.g. a bare list) is handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = "[1, 2, 3]"
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_missing_season_or_episode_returns_none() -> None:
    """A JSON response missing season or episode is treated as no match."""
    mock_response = MagicMock()
    mock_response.content = '{"season": null, "episode": null}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None


@pytest.mark.asyncio
async def test_llm_match_non_integer_season_episode_returns_none() -> None:
    """Non-integer season/episode values in the LLM's JSON are handled gracefully."""
    mock_response = MagicMock()
    mock_response.content = '{"season": "one", "episode": 1}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    # Only ONE execute() call is expected — the initial episode-list query.  The
    # non-integer season/episode values must short-circuit before any S/E lookup.
    session.execute = AsyncMock(return_value=eps_result)

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    assert season is None
    assert episode_num is None
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_llm_match_success_returns_episode() -> None:
    """A valid LLM match resolves to the correct Episode row via a fresh S/E lookup."""
    mock_response = MagicMock()
    mock_response.content = '{"season": 1, "episode": 5}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    matched_episode = _make_episode(ep_id=5, show_id=1, season=1, episode=5)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 5, "The One")]

    match_result = MagicMock()
    match_result.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, match_result])

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is matched_episode
    assert season == 1
    assert episode_num == 5


@pytest.mark.asyncio
async def test_llm_match_markdown_fence_stripped() -> None:
    """JSON wrapped in a code fence is still parsed correctly."""
    mock_response = MagicMock()
    mock_response.content = '```json\n{"season": 2, "episode": 3}\n```'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    matched_episode = _make_episode(ep_id=7, show_id=1, season=2, episode=3)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(2, 3)]
    match_result = MagicMock()
    match_result.scalar_one_or_none.return_value = matched_episode

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, match_result])

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is matched_episode
    assert season == 2
    assert episode_num == 3


@pytest.mark.asyncio
async def test_llm_match_db_lookup_miss_returns_none() -> None:
    """A parsed season/episode with no matching Episode row in the DB returns None."""
    mock_response = MagicMock()
    mock_response.content = '{"season": 9, "episode": 99}'
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(return_value=mock_response)

    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [_make_ep_row(1, 1)]
    miss_result = MagicMock()
    miss_result.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[eps_result, miss_result])

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=_make_entry()
    )
    assert ep is None
    # The proposed season/episode must still be surfaced even though no DB
    # row matched it -- this is what the "No match" event downstream relies on.
    assert season == 9
    assert episode_num == 99


@pytest.mark.asyncio
async def test_llm_match_exception_is_emitted() -> None:
    """A failure is surfaced via on_event, not just the Python logger."""
    events, capture = _event_capture()
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete = AsyncMock(side_effect=RuntimeError("timed out"))

    session = AsyncMock()
    eps_result = MagicMock()
    eps_result.scalars.return_value.all.return_value = [
        _make_episode(ep_id=1, show_id=1, season=1, episode=1)
    ]
    session.execute = AsyncMock(return_value=eps_result)

    entry = ParsedPathEntry(
        raw_path=r"Z:\tv\Show\Show 01.mkv",
        show_dir="Show",
        show_root=r"Z:\tv\Show",
        season=None,
        episode=1,
        is_absolute=True,
    )

    ep, season, episode_num = await llm_match_episode(
        session, llm, show_id=1, show_title="Show", entry=entry, on_event=capture
    )

    assert ep is None
    assert season is None
    assert episode_num is None
    failures = [(lvl, msg) for lvl, msg, _ in events if "episode-list match failed" in msg]
    assert len(failures) == 1
    assert failures[0][0] == "warn"
    assert "timed out" in failures[0][1]

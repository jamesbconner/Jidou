"""Tests for jidou.services.episode_group_mapping.

Fixtures are shaped after the real TMDB episode_groups response for
"Frieren: Beyond Journey's End" (tv id 209867), scaled down for test speed:
a type-6 ("Production") group named "Seasons" that splits one absolute TMDB
season into Specials / Season 1 / Season 2, plus a type-2 ("Absolute") group
for the pure sequential-numbering case.
"""

from unittest.mock import AsyncMock

from jidou.services.episode_group_mapping import (
    GroupBreakdowns,
    _extract_sub_groups,
    fetch_group_breakdowns,
    flatten_for_absolute_numbering,
    resolve_declared_season,
    to_storage_map,
)

_TYPE_6_SUMMARY = {"id": "type6-id", "name": "Seasons", "type": 6, "episode_count": 5}
_TYPE_2_SUMMARY = {"id": "type2-id", "name": "Absolute", "type": 2, "episode_count": 5}

_TYPE_6_DETAIL = {
    "id": "type6-id",
    "name": "Seasons",
    "groups": [
        {
            "name": "Specials",
            "order": 0,
            "episodes": [
                {"id": 901, "season_number": 0, "episode_number": 1, "order": 0},
            ],
        },
        {
            "name": "Season 1",
            "order": 1,
            "episodes": [
                {"id": 101, "season_number": 1, "episode_number": 1, "order": 0},
                {"id": 102, "season_number": 1, "episode_number": 2, "order": 1},
                {"id": 103, "season_number": 1, "episode_number": 3, "order": 2},
            ],
        },
        {
            "name": "Season 2",
            "order": 2,
            "episodes": [
                {"id": 104, "season_number": 1, "episode_number": 4, "order": 0},
                {"id": 105, "season_number": 1, "episode_number": 5, "order": 1},
            ],
        },
    ],
}

_TYPE_2_DETAIL = {
    "id": "type2-id",
    "name": "Absolute",
    "groups": [
        {
            "name": "Absolute",
            "order": 1,
            "episodes": [
                {"id": 101, "season_number": 1, "episode_number": 1, "order": 0},
                {"id": 102, "season_number": 1, "episode_number": 2, "order": 1},
                {"id": 103, "season_number": 1, "episode_number": 3, "order": 2},
                {"id": 104, "season_number": 1, "episode_number": 4, "order": 3},
                {"id": 105, "season_number": 1, "episode_number": 5, "order": 4},
            ],
        },
    ],
}


class TestExtractSubGroups:
    def test_extracts_ordered_pairs_and_excludes_specials(self):
        result = _extract_sub_groups(_TYPE_6_DETAIL)

        assert result == {
            1: [(1, 1), (1, 2), (1, 3)],
            2: [(1, 4), (1, 5)],
        }

    def test_sorts_episodes_by_their_own_order_field_not_response_order(self):
        detail = {
            "groups": [
                {
                    "order": 1,
                    "episodes": [
                        {"id": 2, "season_number": 1, "episode_number": 2, "order": 1},
                        {"id": 1, "season_number": 1, "episode_number": 1, "order": 0},
                    ],
                },
            ],
        }

        result = _extract_sub_groups(detail)

        assert result == {1: [(1, 1), (1, 2)]}

    def test_sub_group_missing_order_is_skipped(self):
        detail = {
            "groups": [
                {"episodes": [{"season_number": 1, "episode_number": 1, "order": 0}]},
            ],
        }

        assert _extract_sub_groups(detail) == {}

    def test_empty_groups_list_returns_empty(self):
        assert _extract_sub_groups({"groups": []}) == {}


class TestFetchGroupBreakdowns:
    async def test_no_episode_groups_returns_empty_without_calling_tmdb(self):
        tmdb = AsyncMock()

        result = await fetch_group_breakdowns(tmdb, None)

        assert result == {}
        tmdb.get_episode_group.assert_not_called()

    async def test_fetches_type_6_and_type_2_when_both_present(self):
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(
            side_effect=lambda group_id: {
                "type6-id": _TYPE_6_DETAIL,
                "type2-id": _TYPE_2_DETAIL,
            }[group_id]
        )

        result = await fetch_group_breakdowns(tmdb, [_TYPE_6_SUMMARY, _TYPE_2_SUMMARY])

        assert result == {
            6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]},
            2: {1: [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)]},
        }
        assert tmdb.get_episode_group.await_count == 2

    async def test_fetches_only_the_type_present(self):
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(return_value=_TYPE_6_DETAIL)

        result = await fetch_group_breakdowns(tmdb, [_TYPE_6_SUMMARY])

        assert set(result) == {6}
        tmdb.get_episode_group.assert_awaited_once_with("type6-id")

    async def test_ignores_group_types_other_than_6_and_2(self):
        tmdb = AsyncMock()
        other_type = {"id": "type7-id", "name": "Cours", "type": 7}

        result = await fetch_group_breakdowns(tmdb, [other_type])

        assert result == {}
        tmdb.get_episode_group.assert_not_called()

    async def test_candidate_missing_id_is_skipped(self):
        tmdb = AsyncMock()
        no_id = {"name": "Seasons", "type": 6}

        result = await fetch_group_breakdowns(tmdb, [no_id])

        assert result == {}
        tmdb.get_episode_group.assert_not_called()

    async def test_fetch_failure_for_one_type_is_logged_and_skipped_not_raised(self):
        tmdb = AsyncMock()
        tmdb.get_episode_group = AsyncMock(
            side_effect=lambda group_id: (
                (_ for _ in ()).throw(Exception("TMDB down"))
                if group_id == "type6-id"
                else _TYPE_2_DETAIL
            )
        )

        result = await fetch_group_breakdowns(tmdb, [_TYPE_6_SUMMARY, _TYPE_2_SUMMARY])

        assert set(result) == {2}


class TestToStorageMap:
    def test_empty_breakdowns_returns_none(self):
        assert to_storage_map({}) is None

    def test_builds_nested_string_keyed_map_with_1_based_positions(self):
        breakdowns: GroupBreakdowns = {6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]}}

        result = to_storage_map(breakdowns)

        assert result == {
            "6": {
                "1": {"1": [1, 1], "2": [1, 2], "3": [1, 3]},
                "2": {"1": [1, 4], "2": [1, 5]},
            }
        }


class TestFlattenForAbsoluteNumbering:
    def test_empty_breakdowns_returns_empty(self):
        assert flatten_for_absolute_numbering({}) == {}

    def test_prefers_type_2_over_type_6_when_both_present(self):
        breakdowns: GroupBreakdowns = {
            6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]},
            2: {1: [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)]},
        }

        result = flatten_for_absolute_numbering(breakdowns)

        assert result == {(1, 1): 1, (1, 2): 2, (1, 3): 3, (1, 4): 4, (1, 5): 5}

    def test_falls_back_to_type_6_when_type_2_absent(self):
        breakdowns: GroupBreakdowns = {6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]}}

        result = flatten_for_absolute_numbering(breakdowns)

        assert result == {(1, 1): 1, (1, 2): 2, (1, 3): 3, (1, 4): 4, (1, 5): 5}

    def test_concatenates_sub_groups_in_order_sequence_not_insertion_order(self):
        breakdowns: GroupBreakdowns = {6: {2: [(1, 4), (1, 5)], 1: [(1, 1), (1, 2), (1, 3)]}}

        result = flatten_for_absolute_numbering(breakdowns)

        assert result[(1, 1)] == 1
        assert result[(1, 4)] == 4


class TestResolveDeclaredSeason:
    def test_none_map_returns_none(self):
        assert resolve_declared_season(None, declared_season=2, episode=1) is None

    def test_empty_map_returns_none(self):
        assert resolve_declared_season({}, declared_season=2, episode=1) is None

    def test_resolves_declared_season_2_episode_1_to_real_season_episode(self):
        stored = to_storage_map({6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]}})

        result = resolve_declared_season(stored, declared_season=2, episode=1)

        assert result == (1, 4)

    def test_prefers_type_6_over_type_2_for_declared_season_lookup(self):
        # Type 6 declares "Season 2" position 1 -> (1, 4). Type 2 has no
        # season-2 grouping at all (it's flat), so this also proves type 6
        # is tried first rather than type 2 winning by being more complete.
        stored = to_storage_map(
            {
                6: {1: [(1, 1), (1, 2), (1, 3)], 2: [(1, 4), (1, 5)]},
                2: {1: [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5)]},
            }
        )

        result = resolve_declared_season(stored, declared_season=2, episode=1)

        assert result == (1, 4)

    def test_unknown_declared_season_returns_none(self):
        stored = to_storage_map({6: {1: [(1, 1), (1, 2), (1, 3)]}})

        assert resolve_declared_season(stored, declared_season=5, episode=1) is None

    def test_unknown_episode_within_known_season_returns_none(self):
        stored = to_storage_map({6: {2: [(1, 4), (1, 5)]}})

        assert resolve_declared_season(stored, declared_season=2, episode=99) is None

"""Tests for jidou.services.tmdb_mapping."""

from unittest.mock import AsyncMock, MagicMock

from jidou.services.tmdb_mapping import build_show_fields, fetch_show_metadata

# ---------------------------------------------------------------------------
# fetch_show_metadata
# ---------------------------------------------------------------------------


async def test_fetch_show_metadata_tv_calls_all_three_endpoints() -> None:
    """A TV fetch calls get_details, get_external_ids, and get_episode_groups."""
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(return_value={"name": "Show"})
    tmdb.get_external_ids = AsyncMock(return_value={"imdb_id": "tt123"})
    tmdb.get_episode_groups = AsyncMock(return_value={"results": [{"id": "g1"}]})

    data = await fetch_show_metadata(tmdb, 42, "tv")

    tmdb.get_details.assert_awaited_once_with(42, media_type="tv")
    tmdb.get_external_ids.assert_awaited_once_with(42, media_type="tv")
    tmdb.get_episode_groups.assert_awaited_once_with(42)
    assert data["name"] == "Show"
    assert data["external_ids"] == {"imdb_id": "tt123"}
    assert data["episode_groups"] == [{"id": "g1"}]


async def test_fetch_show_metadata_movie_skips_episode_groups() -> None:
    """A movie fetch never calls get_episode_groups -- movies have no episode groups."""
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(return_value={"title": "Movie"})
    tmdb.get_external_ids = AsyncMock(return_value={})

    data = await fetch_show_metadata(tmdb, 42, "movie")

    tmdb.get_episode_groups.assert_not_awaited()
    assert data["episode_groups"] == []


async def test_fetch_show_metadata_external_ids_failure_falls_back_to_empty() -> None:
    """A transient get_external_ids failure does not abort the fetch."""
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(return_value={"name": "Show"})
    tmdb.get_external_ids = AsyncMock(side_effect=RuntimeError("network error"))
    tmdb.get_episode_groups = AsyncMock(return_value={"results": []})

    data = await fetch_show_metadata(tmdb, 42, "tv")

    assert data["external_ids"] == {}
    assert data["name"] == "Show"


async def test_fetch_show_metadata_episode_groups_failure_falls_back_to_empty() -> None:
    """A transient get_episode_groups failure does not abort the fetch."""
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(return_value={"name": "Show"})
    tmdb.get_external_ids = AsyncMock(return_value={})
    tmdb.get_episode_groups = AsyncMock(side_effect=RuntimeError("network error"))

    data = await fetch_show_metadata(tmdb, 42, "tv")

    assert data["episode_groups"] == []


async def test_fetch_show_metadata_get_details_failure_propagates() -> None:
    """A get_details failure is not swallowed -- there's no show to build without it."""
    tmdb = AsyncMock()
    tmdb.get_details = AsyncMock(side_effect=RuntimeError("TMDB down"))

    try:
        await fetch_show_metadata(tmdb, 42, "tv")
        raise AssertionError("expected RuntimeError to propagate")
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# build_show_fields — basic mapping
# ---------------------------------------------------------------------------


def test_build_show_fields_tv_uses_name_and_first_air_date() -> None:
    """TV responses map name -> title and first_air_date -> release_date."""
    data = {"name": "TV Show", "first_air_date": "2020-01-01"}
    fields = build_show_fields(data, 42, "tv")

    assert fields["tmdb_id"] == 42
    assert fields["media_type"] == "tv"
    assert fields["title"] == "TV Show"
    assert fields["release_date"] == "2020-01-01"
    assert fields["sys_name"] == "TV Show"


def test_build_show_fields_movie_uses_title_and_release_date() -> None:
    """Movie responses use title/release_date instead of name/first_air_date."""
    data = {"title": "A Movie", "release_date": "2023-06-01"}
    fields = build_show_fields(data, 42, "movie")

    assert fields["title"] == "A Movie"
    assert fields["release_date"] == "2023-06-01"


def test_build_show_fields_title_fallback_used_for_new_show() -> None:
    """title_fallback applies only when there's no existing show to fall back to."""
    fields = build_show_fields({}, 42, "tv", title_fallback="Directory Name")
    assert fields["title"] == "Directory Name"


def test_build_show_fields_defaults_to_empty_title_with_no_fallback() -> None:
    """With neither a TMDB name/title nor a fallback, title is an empty string."""
    fields = build_show_fields({}, 42, "tv")
    assert fields["title"] == ""


def test_build_show_fields_falls_back_to_existing_title() -> None:
    """When updating an existing show, its current title is the fallback."""
    existing = MagicMock()
    existing.title = "Existing Title"
    existing.tmdb_id = 42
    existing.adult = None

    fields = build_show_fields({}, 42, "tv", existing=existing)
    assert fields["title"] == "Existing Title"


def test_build_show_fields_runtime_from_episode_run_time() -> None:
    """runtime falls back to episode_run_time[0] when the runtime key is absent."""
    data = {"name": "Show", "episode_run_time": [42]}
    fields = build_show_fields(data, 1, "tv")
    assert fields["runtime"] == 42


def test_build_show_fields_runtime_prefers_explicit_value() -> None:
    """An explicit runtime key wins over episode_run_time."""
    data = {"name": "Show", "runtime": 90, "episode_run_time": [45]}
    fields = build_show_fields(data, 1, "movie")
    assert fields["runtime"] == 90


def test_build_show_fields_sys_name_sanitized() -> None:
    """sys_name is derived from the resolved title via sanitize_sys_name."""
    fields = build_show_fields({"name": "Re:Zero"}, 1, "tv")
    assert fields["sys_name"] == "Re Zero"


# ---------------------------------------------------------------------------
# build_show_fields — origin_country
# ---------------------------------------------------------------------------


def test_build_show_fields_tv_origin_country_flat_list() -> None:
    """TV origin_country is used as-is when present."""
    data = {"name": "Show", "origin_country": ["JP"]}
    fields = build_show_fields(data, 1, "tv")
    assert fields["origin_country"] == ["JP"]


def test_build_show_fields_movie_production_countries_extracted() -> None:
    """Movie production_countries objects are flattened to ISO codes."""
    data = {
        "title": "Movie",
        "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
    }
    fields = build_show_fields(data, 1, "movie")
    assert fields["origin_country"] == ["US"]


def test_build_show_fields_guards_malformed_production_countries_entry() -> None:
    """A non-dict production_countries entry is skipped, not a crash."""
    data = {
        "title": "Movie",
        "production_countries": ["not-a-dict", {"iso_3166_1": "US"}],
    }
    fields = build_show_fields(data, 1, "movie")
    assert fields["origin_country"] == ["US"]


def test_build_show_fields_production_countries_missing_key_skipped() -> None:
    """A production_countries entry with no iso_3166_1 key is skipped."""
    data = {"title": "Movie", "production_countries": [{"name": "Nowhere"}]}
    fields = build_show_fields(data, 1, "movie")
    assert fields["origin_country"] == []


# ---------------------------------------------------------------------------
# build_show_fields — adult flag same-entity fallback
# ---------------------------------------------------------------------------


def test_build_show_fields_adult_explicit_value_used() -> None:
    """An explicit adult value from TMDB is always used, regardless of existing."""
    fields = build_show_fields({"name": "Show", "adult": True}, 1, "tv")
    assert fields["adult"] is True


def test_build_show_fields_adult_defaults_to_none_for_new_show() -> None:
    """A new show with no adult key and no existing show gets None."""
    fields = build_show_fields({"name": "Show"}, 1, "tv")
    assert fields["adult"] is None


def test_build_show_fields_adult_preserved_on_same_entity_refresh() -> None:
    """An omitted adult field falls back to the existing value on a same-entity refresh."""
    existing = MagicMock()
    existing.title = "Show"
    existing.tmdb_id = 42
    existing.adult = True

    fields = build_show_fields({"name": "Show"}, 42, "tv", existing=existing)
    assert fields["adult"] is True


def test_build_show_fields_adult_cleared_on_identity_change() -> None:
    """An omitted adult field does not carry over when tmdb_id is changing."""
    existing = MagicMock()
    existing.title = "Old Show"
    existing.tmdb_id = 100
    existing.adult = True

    fields = build_show_fields({"name": "New Show"}, 200, "tv", existing=existing)
    assert fields["adult"] is None


# ---------------------------------------------------------------------------
# build_show_fields — external_ids / episode_groups
# ---------------------------------------------------------------------------


def test_build_show_fields_maps_external_ids_and_episode_groups() -> None:
    """external_ids and episode_groups are passed through from the fetched data."""
    data = {
        "name": "Show",
        "external_ids": {"imdb_id": "tt999"},
        "episode_groups": [{"id": "g1"}],
    }
    fields = build_show_fields(data, 1, "tv")
    assert fields["external_ids"] == {"imdb_id": "tt999"}
    assert fields["episode_groups"] == [{"id": "g1"}]


def test_build_show_fields_defaults_external_ids_and_episode_groups_to_empty() -> None:
    """Absent external_ids/episode_groups default to {} / [] rather than None."""
    fields = build_show_fields({"name": "Show"}, 1, "tv")
    assert fields["external_ids"] == {}
    assert fields["episode_groups"] == []


# ---------------------------------------------------------------------------
# build_show_fields — excludes caller-specific fields
# ---------------------------------------------------------------------------


def test_build_show_fields_excludes_caller_specific_fields() -> None:
    """content_type/local_path/aliases/aliases_sources/cached are not TMDB-mapping concerns."""
    fields = build_show_fields({"name": "Show"}, 1, "tv")
    for key in ("content_type", "local_path", "aliases", "aliases_sources", "cached"):
        assert key not in fields

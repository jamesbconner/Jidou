"""Tests for the local show search service."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from jidou.services.show_search import (
    _best_match,
    _escape_like,
    search_local_shows,
)


def _row(
    *,
    id: int,
    title: str,
    aliases: list[str] | None = None,
    sys_name: str | None = None,
    local_path: str | None = None,
) -> SimpleNamespace:
    """Build a result row shaped like the service's column select."""
    return SimpleNamespace(
        id=id,
        tmdb_id=1000 + id,
        title=title,
        media_type="tv",
        content_type="anime",
        local_path=local_path,
        sys_name=sys_name,
        poster_path=None,
        release_date=None,
        aliases=aliases,
    )


def _session(rows: list[SimpleNamespace]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestBestMatch:
    """Field attribution and ranking of a single row."""

    def test_year_suffixed_folder_matches_on_path(self) -> None:
        """The #644 case: remake folder 'Example Show (2019)' is found by its base name."""
        match = _best_match(
            "example show",
            title="Something Else",
            aliases=None,
            sys_name=None,
            local_path="/media/anime/Example Show (2019)",
        )
        assert match is not None
        assert match[1] == "path"

    def test_media_root_directory_does_not_match(self) -> None:
        """Only the folder's final component is searched, never parent directories."""
        assert (
            _best_match(
                "anime",
                title="Other",
                aliases=None,
                sys_name=None,
                local_path="/media/anime/Example Show",
            )
            is None
        )

    def test_exact_beats_prefix_beats_substring(self) -> None:
        exact = _best_match("naruto", title="Naruto", aliases=None, sys_name=None, local_path=None)
        prefix = _best_match(
            "naruto", title="Naruto Shippuden", aliases=None, sys_name=None, local_path=None
        )
        substring = _best_match(
            "naruto", title="Boruto: Naruto Next", aliases=None, sys_name=None, local_path=None
        )
        assert exact and prefix and substring
        assert exact[0] < prefix[0] < substring[0]

    def test_alias_match_is_attributed_to_alias(self) -> None:
        match = _best_match(
            "shingeki",
            title="Attack on Titan",
            aliases=["shingeki no kyojin"],
            sys_name=None,
            local_path=None,
        )
        assert match is not None
        assert match[1] == "alias"

    def test_no_match_returns_none(self) -> None:
        assert (
            _best_match("zzz", title="Abc", aliases=["def"], sys_name="Ghi", local_path="/m/Jkl")
            is None
        )


class TestEscapeLike:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("100%", "100\\%"), ("a_b", "a\\_b"), ("a\\b", "a\\\\b"), ("plain", "plain")],
    )
    def test_escapes_wildcards(self, raw: str, expected: str) -> None:
        assert _escape_like(raw) == expected


class TestSearchLocalShows:
    async def test_short_query_returns_empty_without_querying(self) -> None:
        session = _session([])
        assert await search_local_shows(session, " a ") == []
        session.execute.assert_not_called()

    async def test_ranks_and_labels_results(self) -> None:
        rows = [
            _row(id=1, title="Boruto: Naruto Next Generations"),
            _row(id=2, title="Naruto"),
            _row(id=3, title="Unrelated", local_path="/media/anime/Naruto (2002)"),
            _row(id=4, title="Naruto Shippuden"),
        ]
        hits = await search_local_shows(_session(rows), "Naruto")
        assert [h.id for h in hits] == [2, 4, 3, 1]
        assert hits[0].matched_on == "title"
        assert next(h for h in hits if h.id == 3).matched_on == "path"

    async def test_limit_is_applied_after_ranking(self) -> None:
        rows = [_row(id=i, title=f"Show {i:02d}") for i in range(10)]
        hits = await search_local_shows(_session(rows), "show", limit=3)
        assert len(hits) == 3

    async def test_statement_compiles_for_postgres_with_escaped_pattern(self) -> None:
        session = _session([])
        await search_local_shows(session, "50%_off")
        stmt = session.execute.await_args.args[0]
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "jsonb_array_elements_text" in sql
        assert "regexp_replace" in sql
        assert "%50\\%\\_off%" in compiled.params.values()

    async def test_non_array_aliases_are_guarded_in_sql(self) -> None:
        """Regression: a JSON-null `aliases` made jsonb_array_elements_text raise.

        Postgres errors with "cannot extract elements from a scalar" for a
        JSON null / scalar / object, which 500'd the whole search. The
        statement must only expand values that are arrays.
        """
        session = _session([])
        await search_local_shows(session, "the")
        stmt = session.execute.await_args.args[0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "jsonb_typeof" in sql
        assert "CASE WHEN" in sql

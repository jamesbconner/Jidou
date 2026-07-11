"""Tests for jidou.services.show_lookup."""

from unittest.mock import AsyncMock, MagicMock

from jidou.services.show_lookup import find_show_by_name


def _mock_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


async def test_alias_containment_hit_short_circuits() -> None:
    """An alias-array hit returns immediately, without a title query."""
    show = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result(show))

    result = await find_show_by_name(session, "Attack on Titan")

    assert result is show
    session.execute.assert_awaited_once()


async def test_exact_title_hit_when_alias_misses() -> None:
    """fuzzy=False: alias miss falls through to an exact title match."""
    show = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(show)])

    result = await find_show_by_name(session, "Attack on Titan", fuzzy=False)

    assert result is show
    assert session.execute.await_count == 2


async def test_exact_title_miss_returns_none_without_substring_query() -> None:
    """fuzzy=False never issues a substring query — exactly 2 queries, then None."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(None)])

    result = await find_show_by_name(session, "Daredevil", fuzzy=False)

    assert result is None
    assert session.execute.await_count == 2


async def test_franchise_prefix_false_positive_uses_equality_not_substring() -> None:
    """Regression: "Daredevil" must not resolve to "Daredevil: Born Again".

    Verifies structurally (not just behaviorally) that the non-fuzzy title
    query is an equality comparison, not an ILIKE substring match — so a
    shorter search term can never match a longer title that merely contains it.
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(None)])

    await find_show_by_name(session, "Daredevil", fuzzy=False)

    title_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(title_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIKE" not in compiled.upper()
    assert "=" in compiled


async def test_fuzzy_substring_hit_when_alias_misses() -> None:
    """fuzzy=True: alias miss falls through to a substring title match."""
    show = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(show)])

    result = await find_show_by_name(session, "Daredevil", fuzzy=True)

    assert result is show
    assert session.execute.await_count == 2
    title_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(title_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIKE" in compiled.upper()


async def test_fuzzy_substring_miss_returns_none() -> None:
    """fuzzy=True still returns None when neither alias nor substring hits."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(None)])

    result = await find_show_by_name(session, "Totally Unknown Show", fuzzy=True)

    assert result is None
    assert session.execute.await_count == 2


async def test_fuzzy_and_exact_are_mutually_exclusive_not_stacked() -> None:
    """A single lookup issues exactly one title query — never both exact and fuzzy.

    Exact and fuzzy are alternatives, not stacked fallback tiers: a substring
    match already covers the exact case, so running both would be a wasted query.
    """
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_mock_result(None), _mock_result(None)])

    await find_show_by_name(session, "Show", fuzzy=True)

    assert session.execute.await_count == 2

"""Tests for the runtime application-settings service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.settings_service import (
    CALENDAR_ENABLED,
    DASHBOARD_PAGE_ENABLED,
    DISCOVER_ENABLED,
    RECENT_EPISODES_ENABLED,
    RECENT_EPISODES_PREFER_POSTERS,
    RECENT_MOVIES_ENABLED,
    SHOW_ADULT_CONTENT,
    SIMILAR_TITLES_COUNT,
    SIMILAR_TITLES_ENABLED,
    SIMILAR_TITLES_INCLUDE_EXTERNAL,
    get_all_settings,
    get_setting,
    get_show_adult_content,
    get_similar_titles_count,
    get_similar_titles_enabled,
    get_similar_titles_include_external,
    set_setting,
)


class TestGetSetting:
    @pytest.mark.asyncio
    async def test_returns_default_when_row_absent(self) -> None:
        """get_setting falls back to the provided default when no row exists."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        result = await get_setting(session, "some.key", default="fallback")

        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_returns_stored_value_when_row_present(self) -> None:
        """get_setting returns the row's value when a setting has been set."""
        session = MagicMock()
        row = MagicMock()
        row.value = True
        session.get = AsyncMock(return_value=row)

        result = await get_setting(session, SHOW_ADULT_CONTENT, default=False)

        assert result is True

    @pytest.mark.asyncio
    async def test_default_defaults_to_none(self) -> None:
        """get_setting's default parameter defaults to None when omitted."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        result = await get_setting(session, "unset.key")

        assert result is None


class TestSetSetting:
    @pytest.mark.asyncio
    async def test_executes_upsert_statement(self) -> None:
        """set_setting issues an INSERT ... ON CONFLICT DO UPDATE statement."""
        session = MagicMock()
        session.execute = AsyncMock()

        await set_setting(session, SHOW_ADULT_CONTENT, True)

        session.execute.assert_awaited_once()


class TestGetShowAdultContent:
    @pytest.mark.asyncio
    async def test_defaults_to_false(self) -> None:
        """get_show_adult_content returns False when never explicitly set."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        result = await get_show_adult_content(session)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_enabled(self) -> None:
        """get_show_adult_content returns True once the setting has been enabled."""
        session = MagicMock()
        row = MagicMock()
        row.value = True
        session.get = AsyncMock(return_value=row)

        result = await get_show_adult_content(session)

        assert result is True


class TestGetSimilarTitlesSettings:
    @pytest.mark.asyncio
    async def test_enabled_defaults_to_true(self) -> None:
        """get_similar_titles_enabled returns True when never explicitly set."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        assert await get_similar_titles_enabled(session) is True

    @pytest.mark.asyncio
    async def test_include_external_defaults_to_true(self) -> None:
        """get_similar_titles_include_external returns True by default."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        assert await get_similar_titles_include_external(session) is True

    @pytest.mark.asyncio
    async def test_count_defaults_to_twelve(self) -> None:
        """get_similar_titles_count returns the default when unset."""
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        assert await get_similar_titles_count(session) == 12

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [(0, 1), (-5, 1), (41, 40), (999, 40), (25, 25), ("30", 30)],
    )
    async def test_count_is_clamped(self, stored: object, expected: int) -> None:
        """get_similar_titles_count clamps out-of-range / stringy values to 1..40."""
        session = MagicMock()
        row = MagicMock()
        row.value = stored
        session.get = AsyncMock(return_value=row)

        assert await get_similar_titles_count(session) == expected

    @pytest.mark.asyncio
    async def test_count_falls_back_on_garbage(self) -> None:
        """A non-numeric stored value falls back to the default rather than raising."""
        session = MagicMock()
        row = MagicMock()
        row.value = "not a number"
        session.get = AsyncMock(return_value=row)

        assert await get_similar_titles_count(session) == 12


class TestGetAllSettings:
    @pytest.mark.asyncio
    async def test_fills_defaults_for_unset_keys(self) -> None:
        """get_all_settings returns every known key, using defaults where unset."""
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_all_settings(session)

        assert result == {
            SHOW_ADULT_CONTENT: False,
            CALENDAR_ENABLED: True,
            DASHBOARD_PAGE_ENABLED: True,
            DISCOVER_ENABLED: True,
            RECENT_EPISODES_ENABLED: True,
            RECENT_MOVIES_ENABLED: True,
            RECENT_EPISODES_PREFER_POSTERS: False,
            SIMILAR_TITLES_ENABLED: True,
            SIMILAR_TITLES_COUNT: 12,
            SIMILAR_TITLES_INCLUDE_EXTERNAL: True,
        }

    @pytest.mark.asyncio
    async def test_includes_stored_values(self) -> None:
        """get_all_settings reflects a stored value that overrides the default."""
        session = MagicMock()
        row = MagicMock()
        row.key = SHOW_ADULT_CONTENT
        row.value = True
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_all_settings(session)

        assert result == {
            SHOW_ADULT_CONTENT: True,
            CALENDAR_ENABLED: True,
            DASHBOARD_PAGE_ENABLED: True,
            DISCOVER_ENABLED: True,
            RECENT_EPISODES_ENABLED: True,
            RECENT_MOVIES_ENABLED: True,
            RECENT_EPISODES_PREFER_POSTERS: False,
            SIMILAR_TITLES_ENABLED: True,
            SIMILAR_TITLES_COUNT: 12,
            SIMILAR_TITLES_INCLUDE_EXTERNAL: True,
        }

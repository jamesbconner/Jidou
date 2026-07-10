"""Tests for the runtime application-settings service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jidou.services.settings_service import (
    CALENDAR_ENABLED,
    SHOW_ADULT_CONTENT,
    get_all_settings,
    get_setting,
    get_show_adult_content,
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


class TestGetAllSettings:
    @pytest.mark.asyncio
    async def test_fills_defaults_for_unset_keys(self) -> None:
        """get_all_settings returns every known key, using defaults where unset."""
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        result = await get_all_settings(session)

        assert result == {SHOW_ADULT_CONTENT: False, CALENDAR_ENABLED: True}

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

        assert result == {SHOW_ADULT_CONTENT: True, CALENDAR_ENABLED: True}

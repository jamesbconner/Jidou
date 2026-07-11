"""API routes for runtime-configurable application settings."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.schemas.settings_schema import AppSettingsPatch, AppSettingsRead
from jidou.services.settings_service import (
    CALENDAR_ENABLED,
    RECENT_EPISODES_ENABLED,
    SHOW_ADULT_CONTENT,
    get_all_settings,
    set_setting,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_read_model(values: dict[str, object]) -> AppSettingsRead:
    """Map the service layer's dotted setting keys onto the flat API schema."""
    return AppSettingsRead(
        show_adult_content=bool(values[SHOW_ADULT_CONTENT]),
        calendar_enabled=bool(values[CALENDAR_ENABLED]),
        recent_episodes_enabled=bool(values[RECENT_EPISODES_ENABLED]),
    )


@router.get("", response_model=AppSettingsRead)
async def get_settings(
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AppSettingsRead:
    """Return the current value of every known application setting.

    Args:
        db_session: DB session (injected).

    Returns:
        Current settings, with defaults filled in for any that have never
        been explicitly set.
    """
    values = await get_all_settings(db_session)
    return _to_read_model(values)


@router.patch("", response_model=AppSettingsRead)
async def update_settings(
    payload: AppSettingsPatch,
    db_session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AppSettingsRead:
    """Update one or more application settings.

    Only fields present in the request body are changed; omitted fields are
    left untouched.

    Args:
        payload: Partial settings update.
        db_session: DB session (injected).

    Returns:
        The full settings state after applying the update.
    """
    if "show_adult_content" in payload.model_fields_set:
        await set_setting(db_session, SHOW_ADULT_CONTENT, payload.show_adult_content)
        await db_session.flush()

    if "calendar_enabled" in payload.model_fields_set:
        await set_setting(db_session, CALENDAR_ENABLED, payload.calendar_enabled)
        await db_session.flush()

    if "recent_episodes_enabled" in payload.model_fields_set:
        await set_setting(db_session, RECENT_EPISODES_ENABLED, payload.recent_episodes_enabled)
        await db_session.flush()

    values = await get_all_settings(db_session)
    return _to_read_model(values)

"""API routes for runtime-configurable application settings."""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.database import get_session
from jidou.schemas.settings_schema import AppSettingsPatch, AppSettingsRead
from jidou.services.settings_service import (
    CALENDAR_ENABLED,
    DISCOVER_ENABLED,
    RECENT_EPISODES_ENABLED,
    RECENT_EPISODES_PREFER_POSTERS,
    RECENT_MOVIES_ENABLED,
    SHOW_ADULT_CONTENT,
    SIMILAR_TITLES_COUNT,
    SIMILAR_TITLES_ENABLED,
    SIMILAR_TITLES_INCLUDE_EXTERNAL,
    get_all_settings,
    set_setting,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_read_model(values: dict[str, Any]) -> AppSettingsRead:
    """Map the service layer's dotted setting keys onto the flat API schema."""
    return AppSettingsRead(
        show_adult_content=bool(values[SHOW_ADULT_CONTENT]),
        calendar_enabled=bool(values[CALENDAR_ENABLED]),
        discover_enabled=bool(values[DISCOVER_ENABLED]),
        recent_episodes_enabled=bool(values[RECENT_EPISODES_ENABLED]),
        recent_movies_enabled=bool(values[RECENT_MOVIES_ENABLED]),
        recent_episodes_prefer_posters=bool(values[RECENT_EPISODES_PREFER_POSTERS]),
        similar_titles_enabled=bool(values[SIMILAR_TITLES_ENABLED]),
        similar_titles_count=int(values[SIMILAR_TITLES_COUNT]),
        similar_titles_include_external=bool(values[SIMILAR_TITLES_INCLUDE_EXTERNAL]),
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

    if "discover_enabled" in payload.model_fields_set:
        await set_setting(db_session, DISCOVER_ENABLED, payload.discover_enabled)
        await db_session.flush()

    if "recent_episodes_enabled" in payload.model_fields_set:
        await set_setting(db_session, RECENT_EPISODES_ENABLED, payload.recent_episodes_enabled)
        await db_session.flush()

    if "recent_movies_enabled" in payload.model_fields_set:
        await set_setting(db_session, RECENT_MOVIES_ENABLED, payload.recent_movies_enabled)
        await db_session.flush()

    if "recent_episodes_prefer_posters" in payload.model_fields_set:
        await set_setting(
            db_session, RECENT_EPISODES_PREFER_POSTERS, payload.recent_episodes_prefer_posters
        )
        await db_session.flush()

    if "similar_titles_enabled" in payload.model_fields_set:
        await set_setting(db_session, SIMILAR_TITLES_ENABLED, payload.similar_titles_enabled)
        await db_session.flush()

    if "similar_titles_count" in payload.model_fields_set:
        await set_setting(db_session, SIMILAR_TITLES_COUNT, payload.similar_titles_count)
        await db_session.flush()

    if "similar_titles_include_external" in payload.model_fields_set:
        await set_setting(
            db_session, SIMILAR_TITLES_INCLUDE_EXTERNAL, payload.similar_titles_include_external
        )
        await db_session.flush()

    values = await get_all_settings(db_session)
    return _to_read_model(values)

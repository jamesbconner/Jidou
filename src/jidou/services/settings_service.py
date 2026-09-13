"""Runtime-configurable application settings backed by the app_settings table.

Unlike the env-var-backed values in :mod:`jidou.config` (fixed at process
startup), settings here can be read and updated through the API at any time.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.models.app_setting import AppSetting

SHOW_ADULT_CONTENT = "dashboard.show_adult_content"
CALENDAR_ENABLED = "dashboard.calendar_enabled"
DISCOVER_ENABLED = "dashboard.discover_enabled"
DASHBOARD_PAGE_ENABLED = "pages.dashboard_enabled"
RECENT_EPISODES_ENABLED = "dashboard.recent_episodes_enabled"
RECENT_MOVIES_ENABLED = "dashboard.recent_movies_enabled"
RECENT_EPISODES_PREFER_POSTERS = "dashboard.recent_episodes_prefer_posters"
SIMILAR_TITLES_ENABLED = "recommendations.similar_titles_enabled"
SIMILAR_TITLES_COUNT = "recommendations.similar_titles_count"
SIMILAR_TITLES_INCLUDE_EXTERNAL = "recommendations.similar_titles_include_external"

#: Inclusive bounds for :data:`SIMILAR_TITLES_COUNT`; enforced in the accessor and
#: mirrored by the API schema's ``Field(ge=, le=)`` bounds.
SIMILAR_TITLES_COUNT_MIN = 1
SIMILAR_TITLES_COUNT_MAX = 40

_DEFAULTS: dict[str, Any] = {
    SHOW_ADULT_CONTENT: False,
    CALENDAR_ENABLED: True,
    DISCOVER_ENABLED: True,
    DASHBOARD_PAGE_ENABLED: True,
    RECENT_EPISODES_ENABLED: True,
    RECENT_MOVIES_ENABLED: True,
    RECENT_EPISODES_PREFER_POSTERS: False,
    SIMILAR_TITLES_ENABLED: True,
    SIMILAR_TITLES_COUNT: 12,
    SIMILAR_TITLES_INCLUDE_EXTERNAL: True,
}


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    """Fetch a single setting's value, falling back to *default* when absent.

    Args:
        session: Active async SQLAlchemy session.
        key: Dotted setting name.
        default: Value returned when no row exists for *key*.

    Returns:
        The stored JSON value, or *default* if the setting has never been set.
    """
    row = await session.get(AppSetting, key)
    return row.value if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    """Create or update a single setting.

    Args:
        session: Active async SQLAlchemy session.
        key: Dotted setting name.
        value: Any JSON-serializable value to store.
    """
    stmt = insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})
    await session.execute(stmt)


async def get_show_adult_content(session: AsyncSession) -> bool:
    """Whether adult-flagged shows/episodes should appear on the dashboard.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        ``True`` if adult content should be shown; ``False`` by default.
    """
    return bool(await get_setting(session, SHOW_ADULT_CONTENT, _DEFAULTS[SHOW_ADULT_CONTENT]))


async def get_similar_titles_enabled(session: AsyncSession) -> bool:
    """Whether the show detail page shows a "Similar Titles" carousel.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        ``True`` if the section should be shown; ``True`` by default.
    """
    return bool(
        await get_setting(session, SIMILAR_TITLES_ENABLED, _DEFAULTS[SIMILAR_TITLES_ENABLED])
    )


async def get_similar_titles_count(session: AsyncSession) -> int:
    """How many similar titles to show, clamped to a sane range.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        The configured count, clamped to
        ``[SIMILAR_TITLES_COUNT_MIN, SIMILAR_TITLES_COUNT_MAX]``. Non-integer or
        missing values fall back to the default.
    """
    raw = await get_setting(session, SIMILAR_TITLES_COUNT, _DEFAULTS[SIMILAR_TITLES_COUNT])
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(_DEFAULTS[SIMILAR_TITLES_COUNT])
    return max(SIMILAR_TITLES_COUNT_MIN, min(SIMILAR_TITLES_COUNT_MAX, value))


async def get_similar_titles_include_external(session: AsyncSession) -> bool:
    """Whether similar titles not in the library are included in the carousel.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        ``True`` if titles absent from the library should be shown (with an Add
        action); ``True`` by default.
    """
    return bool(
        await get_setting(
            session,
            SIMILAR_TITLES_INCLUDE_EXTERNAL,
            _DEFAULTS[SIMILAR_TITLES_INCLUDE_EXTERNAL],
        )
    )


async def get_all_settings(session: AsyncSession) -> dict[str, Any]:
    """Fetch every known setting, filling in defaults for unset ones.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        Dict of all known setting keys mapped to their current (or default)
        values.
    """
    stmt = select(AppSetting).where(AppSetting.key.in_(_DEFAULTS.keys()))
    rows = {row.key: row.value for row in (await session.execute(stmt)).scalars().all()}
    return {key: rows.get(key, default) for key, default in _DEFAULTS.items()}

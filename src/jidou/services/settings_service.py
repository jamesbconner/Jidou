"""Runtime-configurable application settings backed by the app_settings table.

Unlike the env-var-backed values in :mod:`jidou.config` (fixed at process
startup), settings here can be read and updated through the API at any time.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jidou.config import settings as env_settings
from jidou.models.app_setting import AppSetting
from jidou.services.schedule_hours import normalize_schedule_hours

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
METADATA_REFRESH_ENABLED = "metadata_refresh.schedule_enabled"
METADATA_REFRESH_HOURS = "metadata_refresh.schedule_hours"
METADATA_REFRESH_LIMIT = "metadata_refresh.limit_per_run"

#: Inclusive bounds for :data:`SIMILAR_TITLES_COUNT`; enforced in the accessor and
#: mirrored by the API schema's ``Field(ge=, le=)`` bounds.
SIMILAR_TITLES_COUNT_MIN = 1
SIMILAR_TITLES_COUNT_MAX = 40

#: Inclusive bounds for :data:`METADATA_REFRESH_LIMIT`; mirrored by the API schema and
#: ``Settings.show_metadata_refresh_limit_per_run``.
METADATA_REFRESH_LIMIT_MIN = 1
METADATA_REFRESH_LIMIT_MAX = 500

#: Last-resort schedule hour if both the stored value and the env default are unusable.
_FALLBACK_REFRESH_HOURS = "4"

# The metadata-refresh values default to the SHOW_METADATA_REFRESH_* environment
# settings, so an existing deployment keeps behaving the same until someone
# changes them on the Settings page.
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
    METADATA_REFRESH_ENABLED: env_settings.show_metadata_refresh_schedule_enabled,
    METADATA_REFRESH_HOURS: env_settings.show_metadata_refresh_schedule_hours,
    METADATA_REFRESH_LIMIT: env_settings.show_metadata_refresh_limit_per_run,
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


async def _get_bool(session: AsyncSession, key: str) -> bool:
    """Read a boolean setting, using its registered default when unset.

    Args:
        session: Active async SQLAlchemy session.
        key: Dotted setting name; must be a key of ``_DEFAULTS``.

    Returns:
        The stored value coerced to ``bool``, or the default.
    """
    return bool(await get_setting(session, key, _DEFAULTS[key]))


async def get_show_adult_content(session: AsyncSession) -> bool:
    """Whether adult-flagged shows/episodes should appear on the dashboard.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        ``True`` if adult content should be shown; ``False`` by default.
    """
    return await _get_bool(session, SHOW_ADULT_CONTENT)


async def get_similar_titles_enabled(session: AsyncSession) -> bool:
    """Whether the show detail page shows a "Similar Titles" carousel.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        ``True`` if the section should be shown; ``True`` by default.
    """
    return await _get_bool(session, SIMILAR_TITLES_ENABLED)


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
    return await _get_bool(session, SIMILAR_TITLES_INCLUDE_EXTERNAL)


async def get_metadata_refresh_schedule_enabled(session: AsyncSession) -> bool:
    """Whether the scheduled show-metadata refresh is switched on.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        The stored value, or the ``SHOW_METADATA_REFRESH_SCHEDULE_ENABLED``
        environment default (``True``) if it has never been set.
    """
    return await _get_bool(session, METADATA_REFRESH_ENABLED)


def resolve_metadata_refresh_hours(stored: object) -> str:
    """The canonical refresh hours to use for a stored (possibly invalid) value.

    A stored value that is not a valid hour list (for example hand-edited in
    the database) is ignored rather than stopping the job from ever running.

    Args:
        stored: Whatever is in the settings table, or the default if unset.

    Returns:
        Sorted, de-duplicated, comma-separated hours such as ``"4,16"``. Falls
        back to the environment default, then to ``"4"``.
    """
    for candidate in (stored, _DEFAULTS[METADATA_REFRESH_HOURS], _FALLBACK_REFRESH_HOURS):
        if not isinstance(candidate, str):
            continue
        try:
            return normalize_schedule_hours(candidate)
        except ValueError:
            continue
    return _FALLBACK_REFRESH_HOURS  # unreachable: the last candidate is always valid


def resolve_metadata_refresh_limit(raw: object) -> int:
    """The per-run refresh limit to use for a stored (possibly invalid) value.

    Args:
        raw: Whatever is in the settings table, or the default if unset.

    Returns:
        *raw* as an int clamped to
        ``[METADATA_REFRESH_LIMIT_MIN, METADATA_REFRESH_LIMIT_MAX]``. Non-integer
        values fall back to ``SHOW_METADATA_REFRESH_LIMIT_PER_RUN``.
    """
    value: int
    try:
        value = int(raw)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        value = int(_DEFAULTS[METADATA_REFRESH_LIMIT])
    return max(METADATA_REFRESH_LIMIT_MIN, min(METADATA_REFRESH_LIMIT_MAX, value))


async def get_metadata_refresh_schedule_hours(session: AsyncSession) -> str:
    """The UTC hours at which the show-metadata refresh is due, canonicalised.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        See :func:`resolve_metadata_refresh_hours`.
    """
    stored = await get_setting(session, METADATA_REFRESH_HOURS, _DEFAULTS[METADATA_REFRESH_HOURS])
    return resolve_metadata_refresh_hours(stored)


async def get_metadata_refresh_limit(session: AsyncSession) -> int:
    """How many shows one metadata-refresh run may refresh, clamped to a sane range.

    Args:
        session: Active async SQLAlchemy session.

    Returns:
        See :func:`resolve_metadata_refresh_limit`.
    """
    raw = await get_setting(session, METADATA_REFRESH_LIMIT, _DEFAULTS[METADATA_REFRESH_LIMIT])
    return resolve_metadata_refresh_limit(raw)


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

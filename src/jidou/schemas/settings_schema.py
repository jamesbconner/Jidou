"""Pydantic schemas for the runtime application-settings API."""

from pydantic import BaseModel, Field, field_validator

from jidou.schemas._base import RequestModel
from jidou.services.schedule_hours import normalize_schedule_hours
from jidou.services.settings_service import (
    METADATA_REFRESH_LIMIT_MAX,
    METADATA_REFRESH_LIMIT_MIN,
    SIMILAR_TITLES_COUNT_MAX,
    SIMILAR_TITLES_COUNT_MIN,
)


class AppSettingsRead(BaseModel):
    """Current value of every known application setting."""

    show_adult_content: bool = Field(
        description="Whether adult-flagged shows/episodes appear on the dashboard",
    )
    calendar_enabled: bool = Field(
        description="Whether the airing calendar page and nav link are shown",
    )
    discover_enabled: bool = Field(
        description="Whether the discover page and nav link are shown",
    )
    dashboard_page_enabled: bool = Field(
        description="Whether the dashboard page and nav link are shown",
    )
    recent_episodes_enabled: bool = Field(
        description="Whether the dashboard's Recently Added Episodes carousel is shown",
    )
    recent_movies_enabled: bool = Field(
        description="Whether the dashboard's Recently Added Movies carousel is shown",
    )
    recent_episodes_prefer_posters: bool = Field(
        description=(
            "Whether the Recently Added Episodes carousel always shows the show poster "
            "instead of the episode still, for visual consistency across cards"
        ),
    )
    similar_titles_enabled: bool = Field(
        description="Whether the show detail page shows a Similar Titles carousel",
    )
    similar_titles_count: int = Field(
        ge=SIMILAR_TITLES_COUNT_MIN,
        le=SIMILAR_TITLES_COUNT_MAX,
        description="How many similar titles to fetch and display",
    )
    similar_titles_include_external: bool = Field(
        description=(
            "Whether similar titles not in the library are included in the carousel "
            "(with an Add action) alongside titles already tracked"
        ),
    )
    metadata_refresh_schedule_enabled: bool = Field(
        description="Whether the scheduled show-metadata refresh runs",
    )
    metadata_refresh_schedule_hours: str = Field(
        description=(
            "UTC hours at which the show-metadata refresh runs, comma-separated "
            "(e.g. '4' or '4,16')"
        ),
    )
    metadata_refresh_limit_per_run: int = Field(
        ge=METADATA_REFRESH_LIMIT_MIN,
        le=METADATA_REFRESH_LIMIT_MAX,
        description="Maximum number of shows one metadata-refresh run refreshes",
    )


class AppSettingsPatch(RequestModel):
    """Partial update payload; only fields present in the request are applied."""

    show_adult_content: bool | None = None
    calendar_enabled: bool | None = None
    discover_enabled: bool | None = None
    dashboard_page_enabled: bool | None = None
    recent_episodes_enabled: bool | None = None
    recent_movies_enabled: bool | None = None
    recent_episodes_prefer_posters: bool | None = None
    similar_titles_enabled: bool | None = None
    similar_titles_count: int | None = Field(
        default=None, ge=SIMILAR_TITLES_COUNT_MIN, le=SIMILAR_TITLES_COUNT_MAX
    )
    similar_titles_include_external: bool | None = None
    metadata_refresh_schedule_enabled: bool | None = None
    metadata_refresh_schedule_hours: str | None = None
    metadata_refresh_limit_per_run: int | None = Field(
        default=None, ge=METADATA_REFRESH_LIMIT_MIN, le=METADATA_REFRESH_LIMIT_MAX
    )

    @field_validator("metadata_refresh_schedule_hours")
    @classmethod
    def _normalise_hours(cls, value: str | None) -> str | None:
        """Reject an invalid hour list and store the canonical form.

        Args:
            value: The submitted hours, or ``None`` when explicitly null.

        Returns:
            The canonical ``"4,16"`` form, or ``None`` unchanged.

        Raises:
            ValueError: If *value* is not a valid comma-separated hour list.
        """
        return None if value is None else normalize_schedule_hours(value)

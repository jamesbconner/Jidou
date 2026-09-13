"""Pydantic schemas for the runtime application-settings API."""

from pydantic import BaseModel, Field


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
        ge=1,
        le=40,
        description="How many similar titles to fetch and display",
    )
    similar_titles_include_external: bool = Field(
        description=(
            "Whether similar titles not in the library are included in the carousel "
            "(with an Add action) alongside titles already tracked"
        ),
    )


class AppSettingsPatch(BaseModel):
    """Partial update payload; only fields present in the request are applied."""

    show_adult_content: bool | None = None
    calendar_enabled: bool | None = None
    discover_enabled: bool | None = None
    dashboard_page_enabled: bool | None = None
    recent_episodes_enabled: bool | None = None
    recent_movies_enabled: bool | None = None
    recent_episodes_prefer_posters: bool | None = None
    similar_titles_enabled: bool | None = None
    similar_titles_count: int | None = Field(default=None, ge=1, le=40)
    similar_titles_include_external: bool | None = None

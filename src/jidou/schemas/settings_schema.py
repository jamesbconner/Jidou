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
    recent_episodes_enabled: bool = Field(
        description="Whether the dashboard's Recently Added Episodes carousel is shown",
    )


class AppSettingsPatch(BaseModel):
    """Partial update payload; only fields present in the request are applied."""

    show_adult_content: bool | None = None
    calendar_enabled: bool | None = None
    recent_episodes_enabled: bool | None = None

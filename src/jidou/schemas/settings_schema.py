"""Pydantic schemas for the runtime application-settings API."""

from pydantic import BaseModel, Field


class AppSettingsRead(BaseModel):
    """Current value of every known application setting."""

    show_adult_content: bool = Field(
        description="Whether adult-flagged shows/episodes appear on the dashboard",
    )


class AppSettingsPatch(BaseModel):
    """Partial update payload; only fields present in the request are applied."""

    show_adult_content: bool | None = None

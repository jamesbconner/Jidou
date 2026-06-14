"""Application configuration via pydantic-settings."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Application
    app_name: str = "Jidou"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://jidou:jidou_dev_password@localhost:5432/jidou"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # TMDB API
    tmdb_api_key: str | None = None
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_rate_limit_per_second: float = Field(default=0.5, ge=0.1, le=2.0)
    tmdb_cache_ttl: int = Field(default=86400, ge=3600)  # 24 hours in seconds

    # CORS
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3100"],
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: str | list[str]) -> list[str]:
        """Allow comma-separated string or JSON array for CORS origins."""
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    # Celery
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        # Use Redis as Celery broker/backend if not explicitly set
        if self.celery_broker_url is None:
            self.celery_broker_url = self.redis_url
        if self.celery_result_backend is None:
            self.celery_result_backend = self.redis_url


# Module-level singleton
settings = Settings()

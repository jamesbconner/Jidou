"""Application configuration via pydantic-settings."""

from pydantic import Field
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

    # CORS — stored as a plain string so pydantic-settings never attempts
    # JSON-parsing. Use the cors_origins property for the parsed list.
    allowed_origins: str = "http://localhost:3100"

    @property
    def cors_origins(self) -> list[str]:
        """Return ALLOWED_ORIGINS as a list, split on commas."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    # SFTP
    sftp_host: str | None = None
    sftp_port: int = 22
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_key_path: str | None = None
    # Comma-separated remote paths to scan, e.g. "/downloads,/completed"
    sftp_remote_paths: str = "/"
    # Full remote path to the YaRSS2 config file managed by Jidou
    rss_config_remote_path: str | None = None
    sftp_max_workers: int = Field(default=8, ge=1, le=32)
    sftp_max_retries: int = Field(default=3, ge=0)
    sftp_retry_delay: float = Field(default=1.0, ge=0.1)

    @property
    def sftp_remote_paths_list(self) -> list[str]:
        """Return SFTP_REMOTE_PATHS as a list, split on commas."""
        return [p.strip() for p in self.sftp_remote_paths.split(",") if p.strip()]

    # Local staging area for downloaded files awaiting parse/match/route
    local_staging_path: str = "/data/staging"

    # Base paths for routed media — used to suggest local_path when resolving unmatched files
    local_tv_path: str = "/data/media/tv"
    local_anime_path: str = "/data/media/anime"
    local_movie_path: str = "/data/media/movies"

    # LLM
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_cache_ttl: int = Field(default=3600, ge=60)
    llm_timeout: float = Field(default=30.0, ge=1.0)

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

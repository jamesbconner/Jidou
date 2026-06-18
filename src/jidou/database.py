"""Database engine and session management for async SQLAlchemy."""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jidou.config import settings
from jidou.models.downloaded_file import DownloadedFile  # noqa: F401
from jidou.models.episode import Episode  # noqa: F401
from jidou.models.show import Show  # noqa: F401
from jidou.models.task import BackgroundTask  # noqa: F401
from jidou.models.watchlist import WatchlistEntry  # noqa: F401

logger = logging.getLogger(__name__)

# Engine created once at startup
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

# Session factory for dependency injection
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield an async database session for FastAPI dependency injection.

    Yields:
        An open AsyncSession that is automatically committed and closed.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Verify database connectivity at startup.

    In production, Alembic manages the schema via migration scripts.
    This function checks that the database is reachable and logs a
    warning if the connection cannot be established — allowing the
    app to start in CI / test environments without a live database.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as exc:
        logger.warning("Database unavailable at startup: %s", exc)


async def close_db() -> None:
    """Dispose the engine connection pool on shutdown."""
    await engine.dispose()

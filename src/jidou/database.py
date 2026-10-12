"""Database engine and session management for async SQLAlchemy."""

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import jidou.models  # noqa: F401 - registers every mapper on Base.metadata
from jidou.config import settings

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


@asynccontextmanager
async def task_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory backed by a fresh engine, disposed on exit.

    Each Celery task runs its own ``asyncio.run()`` loop, so the module-level
    ``engine`` (whose pool is bound to the loop that first used it, or to none
    at all) cannot be shared with workers: reusing it raises stale-pool /
    wrong-loop errors. A task-local engine ties the connection pool to the
    running loop, and disposing it in ``finally`` returns every connection
    before the loop closes.

    Yields:
        An ``async_sessionmaker`` (``pool_pre_ping=True``, ``expire_on_commit=False``)
        bound to the running event loop.

    Example:
        >>> async with task_sessionmaker() as session_factory:  # doctest: +SKIP
        ...     async with session_factory() as session:
        ...         await session.execute(text("SELECT 1"))
    """
    task_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        yield async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await task_engine.dispose()


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

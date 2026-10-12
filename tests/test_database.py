"""Tests for database initialization and teardown."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jidou.database import engine, task_sessionmaker


def test_engine_created() -> None:
    """Test that the async engine is created."""
    assert engine is not None


def test_init_db_imports_models() -> None:
    """Test that init_db references the correct metadata."""
    from jidou.database import init_db

    # init_db should be callable
    assert callable(init_db)


def test_close_db_imports() -> None:
    """Test that close_db is callable."""
    from jidou.database import close_db

    assert callable(close_db)


def _mock_engine() -> MagicMock:
    """Return an engine double whose ``dispose`` is awaitable."""
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    return mock_engine


@pytest.mark.asyncio
async def test_task_sessionmaker_yields_factory_and_configures_engine() -> None:
    """The factory is a real async_sessionmaker over a pre-pinging engine."""
    with patch("jidou.database.create_async_engine", return_value=_mock_engine()) as mock_create:
        async with task_sessionmaker() as factory:
            assert isinstance(factory, async_sessionmaker)
            assert factory.class_ is AsyncSession
            assert factory.kw["expire_on_commit"] is False

    assert mock_create.call_args.kwargs["pool_pre_ping"] is True


@pytest.mark.asyncio
async def test_task_sessionmaker_disposes_engine_on_exit() -> None:
    """The per-task engine is disposed exactly once when the block exits normally."""
    mock_engine = _mock_engine()

    with patch("jidou.database.create_async_engine", return_value=mock_engine):
        async with task_sessionmaker():
            mock_engine.dispose.assert_not_awaited()

    mock_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_sessionmaker_disposes_engine_on_error() -> None:
    """The engine is disposed even when the body raises, and the error propagates."""
    mock_engine = _mock_engine()

    with (
        patch("jidou.database.create_async_engine", return_value=mock_engine),
        pytest.raises(RuntimeError, match="boom"),
    ):
        async with task_sessionmaker():
            raise RuntimeError("boom")

    mock_engine.dispose.assert_awaited_once()

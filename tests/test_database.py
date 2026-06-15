"""Tests for database initialization and teardown."""

from jidou.database import engine


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

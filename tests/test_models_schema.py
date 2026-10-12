"""Guards that hand-written database indexes stay declared in the models.

These indexes already exist in the database via migrations. If a model stops
declaring one, ``alembic check`` (and autogenerate) reports drift, so each
declaration is pinned here without needing a live database.
"""

from sqlalchemy import Index, Table
from sqlalchemy.dialects import postgresql

from jidou.models.episode import Episode
from jidou.models.rss import RssSubscription
from jidou.models.show import Show


def _index_by_name(table: Table, name: str) -> Index:
    """Return the named index declared on ``table``.

    Args:
        table: Table whose declared indexes are searched.
        name: Exact index name.

    Returns:
        The matching ``Index``.

    Raises:
        AssertionError: If the table does not declare an index with that name.
    """
    matches = [ix for ix in table.indexes if ix.name == name]
    assert matches, f"{table.name} does not declare index {name!r}"
    return matches[0]


def test_alias_gin_index_is_declared() -> None:
    """Show.aliases carries the GIN jsonb_path_ops index used by show_lookup."""
    index = _index_by_name(Show.__table__, "ix_shows_aliases_gin")  # type: ignore[arg-type]
    assert index.dialect_options["postgresql"]["using"] == "gin"
    assert index.dialect_options["postgresql"]["ops"] == {"aliases": "jsonb_path_ops"}
    assert [c.name for c in index.columns] == ["aliases"]


def test_stub_per_show_index_is_declared() -> None:
    """RssSubscription allows at most one NULL-remote_key stub per show."""
    index = _index_by_name(
        RssSubscription.__table__,  # type: ignore[arg-type]
        "ix_rss_subscriptions_unique_stub_per_show",
    )
    assert index.unique is True
    assert [c.name for c in index.columns] == ["show_id"]
    where = index.dialect_options["postgresql"]["where"]
    assert str(where.compile(dialect=postgresql.dialect())) == "remote_key IS NULL"


def test_episode_tracking_index_is_declared() -> None:
    """Episode has the composite (show_id, file_tracked) index."""
    index = _index_by_name(
        Episode.__table__,  # type: ignore[arg-type]
        "ix_episodes_show_id_file_tracked",
    )
    assert [c.name for c in index.columns] == ["show_id", "file_tracked"]

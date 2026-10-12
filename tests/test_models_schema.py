"""Guards that hand-written database indexes stay declared in the models.

These indexes already exist in the database via migrations. If a model stops
declaring one, ``alembic check`` (and autogenerate) reports drift, so each
declaration is pinned here without needing a live database.
"""

from enum import StrEnum

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, Table
from sqlalchemy.dialects import postgresql

from jidou.models.downloaded_file import DownloadedFile, FileStatus, IgnoredReason, MatchedBy
from jidou.models.episode import Episode, TrackedSource
from jidou.models.orphan import OrphanedTrackingRecord
from jidou.models.rss import RssConfigSnapshot, RssSubscription, SnapshotType
from jidou.models.show import ContentType, Show, show_columns
from jidou.models.task import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    BackgroundTask,
    TaskStatus,
)
from jidou.models.watchlist import WatchlistEntry, WatchlistStatus


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


# (enum class, mapped column) for every column built with ``str_enum``.
_STR_ENUM_COLUMNS = [
    (FileStatus, DownloadedFile.status),
    (MatchedBy, DownloadedFile.matched_by),
    (IgnoredReason, DownloadedFile.ignored_reason),
    (WatchlistStatus, WatchlistEntry.status),
]


@pytest.mark.parametrize(("enum_cls", "column"), _STR_ENUM_COLUMNS)
def test_str_enum_keeps_pg_type_names(enum_cls: type, column: object) -> None:
    """The Postgres enum type name stays the lower-cased class name (no DDL drift)."""
    assert column.type.name == enum_cls.__name__.lower()  # type: ignore[attr-defined]


@pytest.mark.parametrize(("enum_cls", "column"), _STR_ENUM_COLUMNS)
def test_str_enum_stores_values(enum_cls: type, column: object) -> None:
    """Columns persist member values, not member names."""
    assert column.type.enums == [m.value for m in enum_cls]  # type: ignore[attr-defined]


def test_str_enum_columns_guard_is_not_vacuous() -> None:
    """All four str_enum columns are covered by the parametrized guards."""
    assert len(_STR_ENUM_COLUMNS) == 4


def test_task_status_round_trips_as_value() -> None:
    """BackgroundTask.status binds as the plain value and loads back as the enum."""
    column_type = BackgroundTask.__table__.c.status.type  # type: ignore[attr-defined]
    dialect = postgresql.dialect()
    bind = column_type.bind_processor(dialect)
    result = column_type.result_processor(dialect, None)
    bound = bind(TaskStatus.RUNNING) if bind else TaskStatus.RUNNING
    assert bound == "running"
    assert type(bound) is str
    loaded = result("running") if result else "running"
    assert loaded is TaskStatus.RUNNING


def test_task_status_sets_partition_enum() -> None:
    """Active and terminal sets cover every TaskStatus exactly once."""
    assert set(TaskStatus) == ACTIVE_TASK_STATUSES | TERMINAL_TASK_STATUSES
    assert not ACTIVE_TASK_STATUSES & TERMINAL_TASK_STATUSES
    assert ACTIVE_TASK_STATUSES and TERMINAL_TASK_STATUSES


@pytest.mark.parametrize(
    ("model", "column", "enum_cls", "length"),
    [
        (Show, "content_type", ContentType, 20),
        (Episode, "tracked_source", TrackedSource, 20),
        (OrphanedTrackingRecord, "tracked_source", TrackedSource, 20),
        (RssConfigSnapshot, "snapshot_type", SnapshotType, 32),
    ],
)
def test_vocabulary_columns_are_typed(
    model: type, column: str, enum_cls: type[StrEnum], length: int
) -> None:
    """Vocabulary columns are enum-typed but still plain VARCHAR(n) with no CHECK.

    Pinning ``length`` and ``native_enum`` keeps the DDL identical to the former
    ``String(n)`` columns, so no migration is needed.
    """
    col_type = model.__table__.c[column].type  # type: ignore[attr-defined]
    assert isinstance(col_type, SAEnum)
    assert col_type.enum_class is enum_cls
    assert col_type.length == length
    assert col_type.native_enum is False
    assert not col_type.create_constraint
    # Stored values are the lower-case member values, not member names.
    assert set(col_type.enums) == {m.value for m in enum_cls}


def test_vocabulary_enum_values_match_production_data() -> None:
    """Enums cover every value observed in production (precondition P1)."""
    assert {m.value for m in ContentType} == {"anime", "tv", "movie"}
    assert {m.value for m in TrackedSource} == {"match", "import"}
    assert {m.value for m in SnapshotType} == {"import", "pre_publish", "post_publish"}


def test_every_show_column_has_source() -> None:
    """Every Show column declares its provenance, so show_columns() partitions the table."""
    all_columns = {c.name for c in Show.__table__.columns}
    assert len(all_columns) >= 40
    tagged = [c.name for c in Show.__table__.columns if "source" in c.info]
    assert set(tagged) == all_columns

    buckets = [show_columns(s) for s in ("tmdb", "user", "derived", "key")]
    # Disjoint and exhaustive: each column belongs to exactly one source.
    assert sum(len(b) for b in buckets) == len(all_columns)
    assert frozenset().union(*buckets) == all_columns


def test_show_column_provenance_tagging() -> None:
    """Pin the documented provenance of the non-TMDB columns."""
    assert show_columns("key") == {"id", "tmdb_id", "created_at", "updated_at"}
    assert show_columns("derived") == {"sys_name", "cached", "episode_group_map"}
    assert show_columns("user") == {
        "content_type",
        "local_path",
        "aliases",
        "aliases_sources",
        "active_episode_group_id",
        "active_episode_group_name",
        "list_poster_path",
        "detail_poster_path",
        "banner_path",
        "track_missing_episodes",
    }

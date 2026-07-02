"""Add GIN index on shows.aliases JSONB column.

Revision ID: 0009_perf_indexes
Revises: 0008_rss_feed_active
Create Date: 2026-07-01

Closes #148, #149

Note on watchlist.show_id (#149): the initial schema defines
UniqueConstraint("show_id", name="uq_watchlist_show_id"), which PostgreSQL
backs with a unique B-tree index.  A separate ix_watchlist_show_id would be
redundant, so no additional index is created here.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_perf_indexes"
down_revision = "0008_rss_feed_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # GIN index for alias containment queries (@>). jsonb_path_ops is more
    # compact than the default jsonb_ops and is correct for @>-only queries.
    # CONCURRENTLY is omitted: Alembic wraps migrations in a transaction and
    # PostgreSQL rejects concurrent index builds inside a transaction block.
    # The shows table is small enough that a brief lock during migration is
    # acceptable and far simpler than working around the transaction constraint.
    # SQLite (used in some dev setups) does not support JSONB or GIN indexes.
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_show_aliases_gin "
                "ON shows USING GIN (aliases jsonb_path_ops)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_show_aliases_gin", table_name="shows")

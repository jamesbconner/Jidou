"""Upgrade shows.aliases GIN index to jsonb_path_ops operator class.

Revision ID: 0009_perf_indexes
Revises: 0008_rss_feed_active
Create Date: 2026-07-01

Closes #148, #149

The initial migration (0001_initial) already created ix_shows_aliases_gin
using the default jsonb_ops operator class.  This migration replaces it
with jsonb_path_ops, which is more compact and faster for @> containment
queries (the only operator used in the alias lookup).

Note on watchlist.show_id (#149): the initial schema defines
UniqueConstraint("show_id", name="uq_watchlist_show_id"), which PostgreSQL
backs with a unique B-tree index.  No additional index is needed.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_perf_indexes"
down_revision = "0008_rss_feed_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Drop the default jsonb_ops GIN index added in 0001_initial and
    # recreate it with jsonb_path_ops.  The operator class is more compact
    # and correct for @>-only queries.  SQLite does not support JSONB or GIN.
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_shows_aliases_gin", table_name="shows")
        op.execute(
            sa.text("CREATE INDEX ix_shows_aliases_gin ON shows USING GIN (aliases jsonb_path_ops)")
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_shows_aliases_gin", table_name="shows")
        op.create_index("ix_shows_aliases_gin", "shows", ["aliases"], postgresql_using="gin")

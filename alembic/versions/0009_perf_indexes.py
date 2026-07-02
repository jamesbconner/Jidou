"""Add GIN index on shows.aliases and index on watchlist.show_id.

Revision ID: 0009_perf_indexes
Revises: 0008_rss_feed_active
Create Date: 2026-07-01

Closes #148, #149
"""

from alembic import op

revision = "0009_perf_indexes"
down_revision = "0008_rss_feed_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index for alias containment queries (@>); jsonb_path_ops is more
    # compact than the default jsonb_ops and is the right choice for @> only.
    # CONCURRENTLY avoids locking the table during deployment.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_show_aliases_gin "
        "ON shows USING GIN (aliases jsonb_path_ops)"
    )

    # PostgreSQL does not auto-index FK columns; cascade deletes and
    # watchlist lookups by show_id otherwise require a full table scan.
    op.create_index("ix_watchlist_show_id", "watchlist", ["show_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_show_id", table_name="watchlist")
    op.drop_index("ix_show_aliases_gin", table_name="shows")

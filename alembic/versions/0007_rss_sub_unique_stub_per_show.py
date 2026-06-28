"""Add partial unique index to prevent duplicate RSS stubs per show.

A stub subscription (remote_key IS NULL) is auto-created when a show is added
to the watchlist.  Concurrent inserts could race and create duplicates.  This
partial unique index limits one stub per show while allowing multiple
enabled subscriptions (which always have a remote_key) for the same show.

Revision ID: 0007_rss_sub_unique_stub_per_show
Revises: 0006_add_rss_tables
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_rss_sub_unique_stub_per_show"
down_revision = "0006_add_rss_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_rss_subscriptions_unique_stub_per_show",
        "rss_subscriptions",
        ["show_id"],
        unique=True,
        postgresql_where=sa.text("remote_key IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rss_subscriptions_unique_stub_per_show",
        table_name="rss_subscriptions",
    )

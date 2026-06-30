"""Add active column to rss_feeds table.

Revision ID: 0008_rss_feed_active
Revises: 0007_rss_sub_unique_stub_per_show
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_rss_feed_active"
down_revision = "0007_rss_sub_unique_stub_per_show"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rss_feeds",
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("rss_feeds", "active")

"""Add rss_feeds, rss_subscriptions, and rss_config_snapshots tables.

Revision ID: 0006_add_rss_tables
Revises: 0005_add_task_event_log
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_add_rss_tables"
down_revision = "0005_add_task_event_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_feeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remote_key", sa.String(64), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("default_download_location", sa.String(1024), nullable=True),
        sa.Column("default_move_completed", sa.String(1024), nullable=True),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rss_feeds_remote_key", "rss_feeds", ["remote_key"])

    op.create_table(
        "rss_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("remote_key", sa.String(64), nullable=True),
        sa.Column(
            "feed_id",
            sa.Integer(),
            sa.ForeignKey("rss_feeds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "show_id",
            sa.Integer(),
            sa.ForeignKey("shows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("regex_include", sa.String(1024), nullable=True),
        sa.Column("regex_exclude", sa.String(1024), nullable=True),
        sa.Column("regex_include_ignorecase", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("regex_exclude_ignorecase", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("download_location", sa.String(1024), nullable=True),
        sa.Column("move_completed", sa.String(1024), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("enabled_in_config", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("last_match", sa.String(512), nullable=True),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_rss_subscriptions_remote_key", "rss_subscriptions", ["remote_key"])
    op.create_index("ix_rss_subscriptions_feed_id", "rss_subscriptions", ["feed_id"])
    op.create_index("ix_rss_subscriptions_show_id", "rss_subscriptions", ["show_id"])
    # Partial unique index: remote_key is unique only when non-NULL
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rss_subscriptions_remote_key
        ON rss_subscriptions (remote_key)
        WHERE remote_key IS NOT NULL
        """
    )

    op.create_table(
        "rss_config_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_type", sa.String(32), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("rss_config_snapshots")
    op.execute("DROP INDEX IF EXISTS uq_rss_subscriptions_remote_key")
    op.drop_index("ix_rss_subscriptions_show_id", table_name="rss_subscriptions")
    op.drop_index("ix_rss_subscriptions_feed_id", table_name="rss_subscriptions")
    op.drop_index("ix_rss_subscriptions_remote_key", table_name="rss_subscriptions")
    op.drop_table("rss_subscriptions")
    op.drop_index("ix_rss_feeds_remote_key", table_name="rss_feeds")
    op.drop_table("rss_feeds")

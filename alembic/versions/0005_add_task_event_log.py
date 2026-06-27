"""Add event_log column to background_tasks.

Revision ID: 0005_add_task_event_log
Revises: 0004_add_orphaned_tracking_records
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_add_task_event_log"
down_revision = "0004_add_orphaned_tracking_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    op.add_column(
        "background_tasks",
        sa.Column(
            "event_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("background_tasks", "event_log")

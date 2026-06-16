"""add background_tasks table

Revision ID: 20260616_0002_background_tasks
Revises: 0001_initial
Create Date: 2026-06-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260616_0002_background_tasks"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )
    op.create_index(op.f("ix_background_tasks_celery_task_id"), "background_tasks", ["celery_task_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_background_tasks_celery_task_id"), table_name="background_tasks")
    op.drop_table("background_tasks")

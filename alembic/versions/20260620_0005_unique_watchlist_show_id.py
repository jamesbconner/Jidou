"""Add UNIQUE(show_id) to watchlist table.

Enforces one watchlist entry per show. Without this constraint the
IntegrityError guard in POST /watchlist is dead code — concurrent requests
can both pass the existence check and both insert, creating duplicates.

Revision ID: 20260620_0005_unique_watchlist_show_id
Revises: 20260620_0004_unique_file_remote_path
Create Date: 2026-06-20 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260620_0005_unique_watchlist_show_id"
down_revision: str | None = "20260620_0004_unique_file_remote_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove any pre-existing duplicate show entries; keep the oldest row.
    op.execute("""
        DELETE FROM watchlist w
        USING (
            SELECT MIN(id) AS keep_id, show_id
            FROM watchlist
            GROUP BY show_id
            HAVING COUNT(*) > 1
        ) dups
        WHERE w.show_id = dups.show_id
          AND w.id != dups.keep_id
    """)

    op.create_unique_constraint("uq_watchlist_show_id", "watchlist", ["show_id"])


def downgrade() -> None:
    op.drop_constraint("uq_watchlist_show_id", "watchlist", type_="unique")

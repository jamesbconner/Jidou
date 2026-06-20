"""Add UNIQUE(show_id, remote_path) to downloaded_files.

Resolves the concurrent scan race condition where two overlapping scans
could both insert a DownloadedFile row for the same (show_id, remote_path).
The constraint is enforced at the database level so no application code change
is needed.

NULL semantics: SQL UNIQUE treats NULLs as non-equal, so rows with show_id=NULL
(files not yet assigned to a show) are unaffected by this constraint.

Revision ID: 20260620_0004_unique_file_remote_path
Revises: 20260617_0003_episodes_and_files
Create Date: 2026-06-20 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260620_0004_unique_file_remote_path"
down_revision: str | None = "20260617_0003_episodes_and_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove any pre-existing duplicates before adding the constraint.
    # Keep the row with the lowest id (earliest insert) for each pair.
    op.execute("""
        DELETE FROM downloaded_files df
        USING (
            SELECT MIN(id) AS keep_id, show_id, remote_path
            FROM downloaded_files
            WHERE show_id IS NOT NULL
            GROUP BY show_id, remote_path
            HAVING COUNT(*) > 1
        ) dups
        WHERE df.show_id = dups.show_id
          AND df.remote_path = dups.remote_path
          AND df.id != dups.keep_id
    """)

    op.create_unique_constraint(
        "uq_downloaded_files_show_remote_path",
        "downloaded_files",
        ["show_id", "remote_path"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_downloaded_files_show_remote_path",
        "downloaded_files",
        type_="unique",
    )

"""Schema changes for global scan + media routing pipeline.

Revision ID: 0002_media_routing_schema
Revises: 0001_initial
Create Date: 2026-06-20

Changes:
  shows        — remove remote_path; add content_type, sys_name, aliases (JSONB + GIN)
  filestatus   — add discovered, unmatched, matched enum values
  downloaded_files — replace (show_id, remote_path) unique with remote_path alone;
                     add parsed_show_name, parsed_season, parsed_episode,
                     parsed_confidence, parsed_content_type
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_media_routing_schema"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add new values to the filestatus enum.
    #
    #    PostgreSQL forbids using a new enum value in the same transaction
    #    where it was created (UnsafeNewEnumValueUsageError).  The workaround
    #    is to COMMIT Alembic's wrapping transaction, add the values (they
    #    are immediately committed in the subsequent implicit transaction),
    #    then BEGIN a new transaction for all remaining DDL/DML.
    #
    #    IF NOT EXISTS makes this idempotent on retry.
    # ------------------------------------------------------------------
    conn = op.get_bind()
    conn.execute(sa.text("COMMIT"))
    conn.execute(sa.text("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'discovered'"))
    conn.execute(sa.text("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'unmatched'"))
    conn.execute(sa.text("ALTER TYPE filestatus ADD VALUE IF NOT EXISTS 'matched'"))
    conn.execute(sa.text("BEGIN"))

    # ------------------------------------------------------------------
    # 2. Migrate existing PENDING rows → DISCOVERED.
    #    New enum values are now committed and safe to reference.
    # ------------------------------------------------------------------
    op.execute(
        sa.text("UPDATE downloaded_files SET status = 'discovered' WHERE status = 'pending'")
    )

    # ------------------------------------------------------------------
    # 3. shows — remove remote_path; add content_type, sys_name, aliases.
    # ------------------------------------------------------------------
    op.drop_column("shows", "remote_path")
    op.add_column("shows", sa.Column("content_type", sa.String(length=20), nullable=True))
    op.add_column("shows", sa.Column("sys_name", sa.String(length=500), nullable=True))
    op.add_column(
        "shows", sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.create_index(
        "ix_shows_aliases_gin",
        "shows",
        ["aliases"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # 4. downloaded_files — replace old compound unique with remote_path alone.
    #    First deduplicate any rows that share the same remote_path (possible
    #    when the same file was tracked under different show_ids); keep the
    #    row with the highest id (most recent) and delete the others.
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            DELETE FROM downloaded_files
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM downloaded_files
                GROUP BY remote_path
            )
            """
        )
    )
    op.drop_constraint("uq_downloaded_files_show_remote_path", "downloaded_files", type_="unique")
    op.create_unique_constraint(
        "uq_downloaded_files_remote_path", "downloaded_files", ["remote_path"]
    )

    # ------------------------------------------------------------------
    # 5. downloaded_files — add parsed metadata columns.
    # ------------------------------------------------------------------
    op.add_column(
        "downloaded_files",
        sa.Column("parsed_show_name", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "downloaded_files",
        sa.Column("parsed_season", sa.Integer(), nullable=True),
    )
    op.add_column(
        "downloaded_files",
        sa.Column("parsed_episode", sa.Integer(), nullable=True),
    )
    op.add_column(
        "downloaded_files",
        sa.Column("parsed_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "downloaded_files",
        sa.Column("parsed_content_type", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    # Remove parsed columns
    op.drop_column("downloaded_files", "parsed_content_type")
    op.drop_column("downloaded_files", "parsed_confidence")
    op.drop_column("downloaded_files", "parsed_episode")
    op.drop_column("downloaded_files", "parsed_season")
    op.drop_column("downloaded_files", "parsed_show_name")

    # Restore old unique constraint (requires show_id to be set)
    op.drop_constraint("uq_downloaded_files_remote_path", "downloaded_files", type_="unique")
    op.create_unique_constraint(
        "uq_downloaded_files_show_remote_path", "downloaded_files", ["show_id", "remote_path"]
    )

    # Restore DISCOVERED → PENDING before removing enum value
    op.execute(
        sa.text("UPDATE downloaded_files SET status = 'pending' WHERE status = 'discovered'")
    )

    # Remove shows additions and restore remote_path
    op.drop_index("ix_shows_aliases_gin", table_name="shows")
    op.drop_column("shows", "aliases")
    op.drop_column("shows", "sys_name")
    op.drop_column("shows", "content_type")
    op.add_column("shows", sa.Column("remote_path", sa.String(length=1000), nullable=True))

    # Note: PostgreSQL does not support DROP VALUE on enums.
    # discovered, unmatched, matched remain in the filestatus type after downgrade.

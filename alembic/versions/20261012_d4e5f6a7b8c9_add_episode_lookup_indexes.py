"""add episode lookup indexes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Builds the episode lookup indexes (issue #313) with CREATE INDEX
    CONCURRENTLY so writes to ``episodes`` are not blocked. Concurrent builds
    cannot run inside a transaction, hence the autocommit block.
    """
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_episodes_show_season_episode",
            "episodes",
            ["show_id", "season_number", "episode_number"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_episodes_show_absolute",
            "episodes",
            ["show_id", "absolute_episode_number"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema.

    Drops both indexes concurrently; no data is affected.
    """
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_episodes_show_absolute",
            table_name="episodes",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_episodes_show_season_episode",
            table_name="episodes",
            postgresql_concurrently=True,
        )

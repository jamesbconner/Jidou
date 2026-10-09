"""replace rss_feeds.regex_include_hint with regex_include_samples

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Each feed's single regex_include_hint becomes slot 1 of the new
    regex_include_samples list ({"sample_name": "", "hint": <old value>}), so
    existing guidance is preserved; sample names are filled in by the user later.
    """
    op.add_column(
        "rss_feeds",
        sa.Column("regex_include_samples", postgresql.JSONB(), nullable=True),
    )
    op.execute(
        """
        UPDATE rss_feeds
        SET regex_include_samples = jsonb_build_array(
            jsonb_build_object('sample_name', '', 'hint', regex_include_hint)
        )
        WHERE regex_include_hint IS NOT NULL AND regex_include_hint <> ''
        """
    )
    op.drop_column("rss_feeds", "regex_include_hint")


def downgrade() -> None:
    """Downgrade schema.

    Only slot 1's hint survives the downgrade (the old column held one value).
    """
    op.add_column("rss_feeds", sa.Column("regex_include_hint", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE rss_feeds
        SET regex_include_hint = regex_include_samples -> 0 ->> 'hint'
        WHERE regex_include_samples IS NOT NULL
          AND jsonb_array_length(regex_include_samples) > 0
        """
    )
    op.drop_column("rss_feeds", "regex_include_samples")

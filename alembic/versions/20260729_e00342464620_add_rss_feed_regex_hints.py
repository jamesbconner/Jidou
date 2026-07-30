"""add regex_include_hint and regex_exclude_hint to rss_feeds

Revision ID: e00342464620
Revises: 6d2f4a9c7e13
Create Date: 2026-07-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e00342464620"
down_revision: str | Sequence[str] | None = "6d2f4a9c7e13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Adds a per-feed style guide for the LLM regex suggester
    (POST /rss/subscriptions/{id}/suggest-regex): a representative
    regex_include/regex_exclude shape observed on that feed's own
    subscriptions, used to steer suggestions toward the feed's actual
    release-naming convention instead of a single feed-agnostic prompt.
    NULL means no guidance is set; an empty regex_exclude_hint means the
    feed's releases typically don't need an exclude filter at all.
    """
    op.add_column("rss_feeds", sa.Column("regex_include_hint", sa.Text(), nullable=True))
    op.add_column("rss_feeds", sa.Column("regex_exclude_hint", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("rss_feeds", "regex_exclude_hint")
    op.drop_column("rss_feeds", "regex_include_hint")

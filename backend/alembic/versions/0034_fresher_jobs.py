"""Freshness default 45 -> 14 days: accounts still on the old default move to the new one.

Only the stored value 45 (the old default) changes; anyone who picked another value keeps it.

Revision ID: 5c1e7a9d3f62
Revises: 4b0d6f2a8c51
"""

from alembic import op

revision = "5c1e7a9d3f62"
down_revision = "4b0d6f2a8c51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE profiles SET preferences = jsonb_set(preferences, '{max_age_days}', '14') WHERE (preferences->>'max_age_days')::int = 45")


def downgrade() -> None:
    op.execute("UPDATE profiles SET preferences = jsonb_set(preferences, '{max_age_days}', '45') WHERE (preferences->>'max_age_days')::int = 14")

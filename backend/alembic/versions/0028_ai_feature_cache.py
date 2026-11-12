"""Repeatable AI-scored features: the match fit review cached per exact model + prompt + schema hash

Revision ID: 9c5e1a7b4d06
Revises: 8b4d0f6a3c95
Create Date: 2026-11-13 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c5e1a7b4d06"
down_revision: Union[str, Sequence[str], None] = "8b4d0f6a3c95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_feature_cache",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_feature_cache_user", "ai_feature_cache", ["user_id"])
    op.create_index("ix_ai_feature_cache_created", "ai_feature_cache", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_feature_cache")

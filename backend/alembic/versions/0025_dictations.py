"""Dictation metrics (no audio, no text): per-stage latency and the Dictation Edit Rate

Revision ID: 6f2b8d4e1a73
Revises: 5e1a7c3d9f68
Create Date: 2026-11-12 18:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "6f2b8d4e1a73"
down_revision: Union[str, Sequence[str], None] = "5e1a7c3d9f68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=20), server_default="interview", nullable=False),
        sa.Column("model", sa.String(length=60), server_default="", nullable=False),
        sa.Column("fallback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("retried", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("audio_ms", sa.Integer(), nullable=True),
        sa.Column("words", sa.Integer(), server_default="0", nullable=False),
        sa.Column("corrections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("asr_ms", sa.Integer(), nullable=True),
        sa.Column("server_ms", sa.Integer(), nullable=True),
        sa.Column("client_ms", sa.Integer(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=True),
        sa.Column("edit_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dictations_user_created", "dictations", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("dictations")

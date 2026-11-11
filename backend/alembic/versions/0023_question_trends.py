"""Trend-refreshed interview questions: the question bank and each field's rising skills

Revision ID: 4d0f6b2c8e57
Revises: 3c9e5a1b7d46
Create Date: 2026-11-11 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '4d0f6b2c8e57'
down_revision: Union[str, Sequence[str], None] = '3c9e5a1b7d46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_bank",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("industry", sa.String(30), nullable=False),
        sa.Column("round_kind", sa.String(20), nullable=False),
        sa.Column("skill", sa.String(80), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(20), nullable=False, server_default="baseline"),
        sa.Column("growth", sa.Float()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_qbank_industry_active", "question_bank", ["industry", "active"])
    op.create_table(
        "industry_trends",
        sa.Column("industry", sa.String(30), primary_key=True),
        sa.Column("skills", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("postings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="baseline"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("industry_trends")
    op.drop_index("ix_qbank_industry_active", table_name="question_bank")
    op.drop_table("question_bank")

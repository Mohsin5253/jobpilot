"""Scam Shield + Verifier v2: verifications, scam_reports, and per-job verification / ghost score

`jobs` is the opportunities table (extended, not duplicated): + verification_id, repost_count, ghost_score.
verifications rows come from both the public Scam Shield (opportunity_id NULL, checks without evidence) and the
pipeline Verifier (opportunity_id set). Pasted text is never stored; scam_reports hold an opt-in redacted copy.

Revision ID: 3e9a71c4d2b0
Revises: 0c5d2a7e8b11
Create Date: 2026-11-10 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '3e9a71c4d2b0'
down_revision: Union[str, Sequence[str], None] = '0c5d2a7e8b11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'verifications',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('opportunity_id', sa.Uuid(), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('source', sa.String(length=20), server_default='public', nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False, index=True),
        sa.Column('verdict', sa.String(length=20), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('checks', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('ghost_score', sa.Integer(), nullable=True),
        sa.Column('llm_category', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_table(
        'scam_reports',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('verification_id', sa.Uuid(), sa.ForeignKey('verifications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('redacted_text', sa.Text(), nullable=False),
        sa.Column('reporter_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='new', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column('jobs', sa.Column('verification_id', sa.Uuid(), sa.ForeignKey('verifications.id', ondelete='SET NULL'), nullable=True))
    op.add_column('jobs', sa.Column('repost_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('jobs', sa.Column('ghost_score', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'ghost_score')
    op.drop_column('jobs', 'repost_count')
    op.drop_column('jobs', 'verification_id')
    op.drop_table('scam_reports')
    op.drop_table('verifications')

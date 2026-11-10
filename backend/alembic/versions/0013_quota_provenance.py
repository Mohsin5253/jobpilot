"""Quality quota and approval events (F5); claim provenance lives in tailored_resumes.bullets (F3)

Extends instead of duplicating: "applications" are outreach_drafts (+ job_matches), so the per-application
send_worthiness goes on outreach_drafts; tailored bullets keep their source_refs / revert_reason inside
tailored_resumes.bullets JSONB. New: quotas (one row per user per IST day) and approval_events (every approve,
reject and send, with its channel). users.daily_send_cap holds the student's chosen cap (default 5).

Revision ID: 5a1d8c3f7e92
Revises: 3e9a71c4d2b0
Create Date: 2026-11-10 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5a1d8c3f7e92'
down_revision: Union[str, Sequence[str], None] = '3e9a71c4d2b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('daily_send_cap', sa.Integer(), server_default='5', nullable=False))
    op.add_column('outreach_drafts', sa.Column('send_worthiness', sa.Integer(), nullable=True))
    op.add_column('outreach_drafts', sa.Column('approval_channel', sa.String(length=20), nullable=True))
    op.create_table(
        'quotas',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('date', sa.Date(), primary_key=True),
        sa.Column('sends_used', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cap', sa.Integer(), nullable=False),
    )
    op.create_table(
        'approval_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('outreach_drafts.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('channel', sa.String(length=20), server_default='web', nullable=False),
        sa.Column('ip_hash', sa.String(length=64), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('approval_events')
    op.drop_table('quotas')
    op.drop_column('outreach_drafts', 'approval_channel')
    op.drop_column('outreach_drafts', 'send_worthiness')
    op.drop_column('users', 'daily_send_cap')

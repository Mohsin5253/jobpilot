"""Stipend & PPO ledger (F7), JD-specific mock interviews (F9), gap-to-proof projects (F10)

Companies are keyed by a normalised name (company_key) rather than a separate companies table: postings already
carry the company name, and the ledger only needs to group by it.

Revision ID: e7b1d9f2a684
Revises: d2a6f1c8e357
Create Date: 2026-11-11 00:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e7b1d9f2a684'
down_revision: Union[str, Sequence[str], None] = 'd2a6f1c8e357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stipend_reports',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('company', sa.String(length=200), nullable=False),
        sa.Column('company_key', sa.String(length=200), nullable=False, index=True),
        sa.Column('role', sa.String(length=200), server_default='', nullable=False),
        sa.Column('stipend', sa.Integer(), nullable=False),  # INR per month
        sa.Column('duration_months', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),  # remote | onsite | hybrid
        sa.Column('ppo_offered', sa.Boolean(), nullable=False),
        sa.Column('paid_on_time', sa.Boolean(), nullable=False),
        sa.Column('verified_via', sa.String(length=20), server_default='none', nullable=False),  # none | college_email | offer_letter
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),  # pending | published | flagged | rejected
        sa.Column('doc_enc', sa.LargeBinary(), nullable=True),  # offer letter, encrypted, deleted once checked
        sa.Column('doc_hash', sa.String(length=64), nullable=True),
        sa.Column('otp_hash', sa.String(length=64), nullable=True),
        sa.Column('otp_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'interview_sessions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('job_matches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'gap_projects',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('match_id', sa.Uuid(), sa.ForeignKey('job_matches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('skill', sa.String(length=80), nullable=False),
        sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='proposed', nullable=False),  # proposed | verified | rejected
        sa.Column('repo_url', sa.String(length=300), nullable=True),
        sa.Column('before_score', sa.Float(), nullable=True),
        sa.Column('after_score', sa.Float(), nullable=True),
        sa.Column('run_id', sa.Uuid(), sa.ForeignKey('agent_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('gap_projects')
    op.drop_table('interview_sessions')
    op.drop_table('stipend_reports')

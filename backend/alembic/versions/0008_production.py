"""production: shared ingestion, accounts, plans, per-user mail

Revision ID: 5d1e7a2c9b40
Revises: 82b8ca0e66bf
Create Date: 2026-11-04 12:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5d1e7a2c9b40'
down_revision: Union[str, Sequence[str], None] = '82b8ca0e66bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('plan', sa.String(length=20), server_default='free', nullable=False))
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('is_demo', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('pro_interest_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_users_expires_at'), 'users', ['expires_at'], unique=False)
    op.add_column('jobs', sa.Column('entry_level', sa.Boolean(), server_default='false', nullable=False))
    op.create_index('ix_jobs_fetched_at', 'jobs', ['fetched_at'], unique=False)

    op.create_table(
        'source_targets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('target', sa.String(length=300), nullable=False),
        sa.Column('demand', sa.Integer(), server_default='0', nullable=False),
        sa.Column('fetch_prefs', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('next_due_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(length=300), server_default='', nullable=False),
        sa.Column('failures', sa.Integer(), server_default='0', nullable=False),
        sa.Column('postings', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'target', name='uq_source_target'),
    )
    op.create_index('ix_source_targets_due', 'source_targets', ['next_due_at'], unique=False)
    op.create_table(
        'board_probes',
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('slug'),
    )
    op.create_table(
        'rate_limits',
        sa.Column('key', sa.String(length=300), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('key', 'window_start'),
    )
    op.create_table(
        'password_resets',
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token_hash'),
    )
    op.create_index(op.f('ix_password_resets_user_id'), 'password_resets', ['user_id'], unique=False)
    op.create_table(
        'mail_accounts',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=320), nullable=False),
        sa.Column('from_email', sa.String(length=320), nullable=False),
        sa.Column('from_name', sa.String(length=200), nullable=False),
        sa.Column('password_enc', sa.Text(), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('mail_accounts')
    op.drop_index(op.f('ix_password_resets_user_id'), table_name='password_resets')
    op.drop_table('password_resets')
    op.drop_table('rate_limits')
    op.drop_table('board_probes')
    op.drop_index('ix_source_targets_due', table_name='source_targets')
    op.drop_table('source_targets')
    op.drop_index('ix_jobs_fetched_at', table_name='jobs')
    op.drop_column('jobs', 'entry_level')
    op.drop_index(op.f('ix_users_expires_at'), table_name='users')
    for col in ('last_seen_at', 'pro_interest_at', 'expires_at', 'is_demo', 'is_admin', 'plan', 'token_version'):
        op.drop_column('users', col)

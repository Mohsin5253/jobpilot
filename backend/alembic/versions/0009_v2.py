"""v2: consent, extension tokens, proof pack, referrals, outcomes, ghost risk, campus, WhatsApp

Revision ID: 7a3c2e9d1f55
Revises: 5d1e7a2c9b40
Create Date: 2026-11-04 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '7a3c2e9d1f55'
down_revision: Union[str, Sequence[str], None] = '5d1e7a2c9b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column('profiles', sa.Column('evidence', JSONB, server_default='{}', nullable=False))
    op.add_column('profiles', sa.Column('academics', JSONB, server_default='{}', nullable=False))
    op.add_column('profiles', sa.Column('proof_slug', sa.String(length=40), nullable=True))
    op.create_unique_constraint('uq_profiles_proof_slug', 'profiles', ['proof_slug'])
    op.add_column('profiles', sa.Column('whatsapp_number', sa.String(length=20), nullable=True))
    op.add_column('profiles', sa.Column('whatsapp_hour_local', sa.Integer(), server_default='8', nullable=False))
    op.add_column('profiles', sa.Column('whatsapp_last_sent_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('jobs', sa.Column('ghost_risk', sa.String(length=10), server_default='low', nullable=False))
    op.add_column('jobs', sa.Column('ghost_reasons', JSONB, server_default='[]', nullable=False))

    op.add_column('job_matches', sa.Column('outcome', sa.String(length=20), server_default='none', nullable=False))
    op.add_column('job_matches', sa.Column('outcome_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('job_matches', sa.Column('rejection_reason', sa.String(length=300), server_default='', nullable=False))
    op.add_column('job_matches', sa.Column('resume_variant', sa.String(length=2), server_default='A', nullable=False))
    op.add_column('job_matches', sa.Column('ppo_status', sa.String(length=20), server_default='none', nullable=False))

    op.add_column('outreach_drafts', sa.Column('kind', sa.String(length=20), server_default='application', nullable=False))

    op.create_table(
        'consents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('purpose', sa.String(length=30), nullable=False),
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_consent_user_purpose', 'consents', ['user_id', 'purpose'])
    op.create_table(
        'api_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=12), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_api_tokens_user_id'), 'api_tokens', ['user_id'])
    op.create_table(
        'organizations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('invite_code', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
        sa.UniqueConstraint('invite_code'),
    )
    op.create_table(
        'org_members',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_org_member_user'),
    )
    op.create_index(op.f('ix_org_members_org_id'), 'org_members', ['org_id'])
    op.create_table(
        'campus_drives',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=True),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('company', sa.String(length=200), nullable=False),
        sa.Column('role', sa.String(length=200), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('compensation', sa.String(length=100), nullable=False),
        sa.Column('eligibility', JSONB, server_default='{}', nullable=False),
        sa.Column('register_by', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rounds', JSONB, server_default='[]', nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_campus_drives_org_id'), 'campus_drives', ['org_id'])
    op.create_index(op.f('ix_campus_drives_user_id'), 'campus_drives', ['user_id'])
    op.create_table(
        'drive_statuses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('drive_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('round_index', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['drive_id'], ['campus_drives.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('drive_id', 'user_id', name='uq_drive_user'),
    )
    op.create_index(op.f('ix_drive_statuses_user_id'), 'drive_statuses', ['user_id'])


def downgrade() -> None:
    for t in ('drive_statuses', 'campus_drives', 'org_members', 'organizations', 'api_tokens', 'consents'):
        op.drop_table(t)
    op.drop_column('outreach_drafts', 'kind')
    for c in ('ppo_status', 'resume_variant', 'rejection_reason', 'outcome_at', 'outcome'):
        op.drop_column('job_matches', c)
    op.drop_column('jobs', 'ghost_reasons')
    op.drop_column('jobs', 'ghost_risk')
    op.drop_constraint('uq_profiles_proof_slug', 'profiles', type_='unique')
    for c in ('whatsapp_last_sent_at', 'whatsapp_hour_local', 'whatsapp_number', 'proof_slug', 'academics', 'evidence'):
        op.drop_column('profiles', c)

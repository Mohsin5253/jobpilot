"""Signed Proof Links (F4): one per approved application, Ed25519-signed, with a server-side view log

Revision ID: 7c2f9e4b1a63
Revises: 5a1d8c3f7e92
Create Date: 2026-11-10 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '7c2f9e4b1a63'
down_revision: Union[str, Sequence[str], None] = '5a1d8c3f7e92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'proof_links',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('application_id', sa.Uuid(), sa.ForeignKey('outreach_drafts.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False, unique=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('signature', sa.String(length=128), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('views_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_viewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'proof_link_views',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('proof_link_id', sa.Uuid(), sa.ForeignKey('proof_links.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('ua_family', sa.String(length=30), server_default='other', nullable=False),
    )


def downgrade() -> None:
    op.drop_table('proof_link_views')
    op.drop_table('proof_links')

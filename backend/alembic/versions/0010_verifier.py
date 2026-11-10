"""Verifier agent: a legitimacy verdict on every job

Revision ID: 9b4e1f6a2c73
Revises: 7a3c2e9d1f55
Create Date: 2026-11-09 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9b4e1f6a2c73'
down_revision: Union[str, Sequence[str], None] = '7a3c2e9d1f55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('legit_status', sa.String(length=12), nullable=True))
    op.add_column('jobs', sa.Column('legit_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('jobs', sa.Column('legit_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'legit_checked_at')
    op.drop_column('jobs', 'legit_reasons')
    op.drop_column('jobs', 'legit_status')

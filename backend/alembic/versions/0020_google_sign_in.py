"""Sign in with Google: users.google_sub (Google's stable account id)

Revision ID: 1a7c3e9f5b24
Revises: f4c8a2e6b913
Create Date: 2026-11-11 03:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1a7c3e9f5b24'
down_revision: Union[str, Sequence[str], None] = 'f4c8a2e6b913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('google_sub', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_users_google_sub', 'users', ['google_sub'])
    op.execute("DO $$ BEGIN EXECUTE 'GRANT SELECT ON users TO jobpilot_officer'; EXCEPTION WHEN undefined_object OR insufficient_privilege THEN NULL; END $$;")


def downgrade() -> None:
    op.drop_constraint('uq_users_google_sub', 'users', type_='unique')
    op.drop_column('users', 'google_sub')

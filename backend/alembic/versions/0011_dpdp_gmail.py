"""DPDP: itemized consent records, rights requests, age gate, inactivity notice; Gmail OAuth sending

Extends the existing tables instead of duplicating them:
  consents       version -> notice_version, + method, guardian_user_id
  mail_accounts  + provider (smtp | gmail_oauth), refresh_token_enc, last_sent_at; password_enc nullable
  users          + adult_confirmed_at, inactivity_notice_at
New: rights_requests (access / correction / erasure / grievance / nomination, 30-day due date).
Users who already connected a mailbox get a 'sending' consent recorded as method='migrated'.

Revision ID: 0c5d2a7e8b11
Revises: 9b4e1f6a2c73
Create Date: 2026-11-10 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0c5d2a7e8b11'
down_revision: Union[str, Sequence[str], None] = '9b4e1f6a2c73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('consents', 'version', new_column_name='notice_version')
    op.add_column('consents', sa.Column('method', sa.String(length=30), server_default='checkbox', nullable=False))
    op.add_column('consents', sa.Column('guardian_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))

    op.add_column('mail_accounts', sa.Column('provider', sa.String(length=20), server_default='smtp', nullable=False))
    op.add_column('mail_accounts', sa.Column('refresh_token_enc', sa.Text(), nullable=True))
    op.add_column('mail_accounts', sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('mail_accounts', 'password_enc', existing_type=sa.Text(), nullable=True)

    op.add_column('users', sa.Column('adult_confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('inactivity_notice_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'rights_requests',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('contact_email', sa.String(length=320), server_default='', nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('details', sa.Text(), server_default='', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
        sa.Column('response', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_rights_status_due', 'rights_requests', ['status', 'due_at'])

    op.execute(
        "INSERT INTO consents (id, user_id, purpose, notice_version, method) "
        "SELECT gen_random_uuid(), m.user_id, 'sending', '2026-11', 'migrated' FROM mail_accounts m"
    )


def downgrade() -> None:
    op.execute("DELETE FROM consents WHERE purpose = 'sending'")
    op.drop_index('ix_rights_status_due', table_name='rights_requests')
    op.drop_table('rights_requests')
    op.drop_column('users', 'inactivity_notice_at')
    op.drop_column('users', 'adult_confirmed_at')
    op.execute("DELETE FROM mail_accounts WHERE password_enc IS NULL")
    op.alter_column('mail_accounts', 'password_enc', existing_type=sa.Text(), nullable=False)
    op.drop_column('mail_accounts', 'last_sent_at')
    op.drop_column('mail_accounts', 'refresh_token_enc')
    op.drop_column('mail_accounts', 'provider')
    op.drop_column('consents', 'guardian_user_id')
    op.drop_column('consents', 'method')
    op.alter_column('consents', 'notice_version', new_column_name='version')

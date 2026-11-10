"""WhatsApp approvals + language (F6): users.language, and processed WhatsApp message ids for idempotency

Revision ID: b8e3c5a17d40
Revises: 9d4b6a2e5c18
Create Date: 2026-11-10 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8e3c5a17d40'
down_revision: Union[str, Sequence[str], None] = '9d4b6a2e5c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('language', sa.String(length=5), server_default='en', nullable=False))
    op.create_table(
        'whatsapp_events',
        sa.Column('id', sa.String(length=128), primary_key=True),  # the Cloud API message id (wamid)
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('whatsapp_events')
    op.drop_column('users', 'language')

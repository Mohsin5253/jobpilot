"""Mock interviews v2: industry rounds, the chosen interviewer, and integrity (proctoring) records

Revision ID: 3c9e5a1b7d46
Revises: 2b8d4f0a6c35
Create Date: 2026-11-11 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '3c9e5a1b7d46'
down_revision: Union[str, Sequence[str], None] = '2b8d4f0a6c35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("interview_sessions", sa.Column("integrity", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("interview_sessions", sa.Column("status", sa.String(20), nullable=False, server_default="active"))


def downgrade() -> None:
    op.drop_column("interview_sessions", "status")
    op.drop_column("interview_sessions", "integrity")
    op.drop_column("interview_sessions", "meta")

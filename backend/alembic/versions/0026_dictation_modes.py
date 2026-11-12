"""Dictation modes: polished (Flow clean-up behind guardrails) or word for word; guard result and clean-up latency

Revision ID: 7a3c9e5f2b84
Revises: 6f2b8d4e1a73
Create Date: 2026-11-12 21:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a3c9e5f2b84"
down_revision: Union[str, Sequence[str], None] = "6f2b8d4e1a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dictations", sa.Column("mode", sa.String(length=12), server_default="verbatim", nullable=False))
    op.add_column("dictations", sa.Column("guard", sa.String(length=40), server_default="", nullable=False))
    op.add_column("dictations", sa.Column("llm_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    for c in ("llm_ms", "guard", "mode"):
        op.drop_column("dictations", c)

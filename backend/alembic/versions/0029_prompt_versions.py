"""Prompt version per AI call: a hash of the system prompt (never its text), next to the model id

Revision ID: 0d6f2b8c5e17
Revises: 9c5e1a7b4d06
Create Date: 2026-11-13 15:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0d6f2b8c5e17"
down_revision: Union[str, Sequence[str], None] = "9c5e1a7b4d06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("prompt_version", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "prompt_version")

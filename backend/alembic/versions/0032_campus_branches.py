"""Campus branches: one college name, several branches with different fields (e.g. an engineering branch and a law
branch), each its own campus under the same institution, with its own staff, codes, programmes and up to 20 lakh
students.

Revision ID: 3a9c5e1f7b40
Revises: 2f8b4d0e6a39
Create Date: 2026-11-13 23:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3a9c5e1f7b40"
down_revision: Union[str, Sequence[str], None] = "2f8b4d0e6a39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campuses", sa.Column("branch", sa.String(length=120), server_default="", nullable=False))
    op.execute("CREATE UNIQUE INDEX uq_campus_branch ON campuses (institution_id, lower(name), lower(branch))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_campus_branch")
    op.drop_column("campuses", "branch")

"""cost columns to 8 decimal places (sub-cent Groq calls)

Revision ID: 0002_cost_precision
Revises: 9149bb249446
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_cost_precision"
down_revision = "9149bb249446"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("llm_calls", "agent_runs"):
        op.alter_column(table, "cost_usd", type_=sa.Numeric(14, 8), existing_type=sa.Numeric(12, 6))


def downgrade() -> None:
    for table in ("llm_calls", "agent_runs"):
        op.alter_column(table, "cost_usd", type_=sa.Numeric(12, 6), existing_type=sa.Numeric(14, 8))

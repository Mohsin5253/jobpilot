"""Campus v2: indexes that match each staff list's filter and order exactly (campus, [department | batch | status],
created_at DESC, id DESC), so a keyset page reads 51 index entries instead of sorting a whole campus.

Revision ID: 2f8b4d0e6a39
Revises: 1e7a3c9d5f28
Create Date: 2026-11-13 21:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "2f8b4d0e6a39"
down_revision: Union[str, Sequence[str], None] = "1e7a3c9d5f28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = {
    "ix_roster_list": "roster_students (campus_id, created_at DESC, id DESC)",
    "ix_roster_dept_list": "roster_students (campus_id, department_id, created_at DESC, id DESC)",
    "ix_roster_batch_list": "roster_students (campus_id, batch_id, created_at DESC, id DESC)",
    "ix_achievements_status_list": "student_achievements (campus_id, status, created_at DESC, id DESC)",
}


def upgrade() -> None:
    for name, spec in INDEXES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}")
    op.execute("DROP INDEX IF EXISTS ix_roster_scope")  # superseded by the two above


def downgrade() -> None:
    for name in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_roster_scope ON roster_students (campus_id, department_id, batch_id, created_at, id)")

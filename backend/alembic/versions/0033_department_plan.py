"""Department plan: a department (Computer Science, ECS...) registers itself, is verified by JobPilot, and is run by its
HOD with up to 300 students. Campuses get a plan, departments their own staff code, and registrations a queue.

Revision ID: 4b0d6f2a8c51
Revises: 3a9c5e1f7b40
Create Date: 2026-11-14 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4b0d6f2a8c51"
down_revision: Union[str, Sequence[str], None] = "3a9c5e1f7b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campuses", sa.Column("plan", sa.String(length=20), server_default="college", nullable=False))  # pilot | department | college | university
    op.add_column("departments", sa.Column("staff_code_hash", sa.String(length=64), nullable=True))
    op.add_column("departments", sa.Column("staff_code_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("departments", sa.Column("plan_limit", sa.Integer(), nullable=True))  # 300 on the Department plan
    op.execute("CREATE INDEX ix_departments_staff_code ON departments (staff_code_hash) WHERE staff_code_hash IS NOT NULL")
    op.add_column("email_otps", sa.Column("department_id", sa.Uuid(), nullable=True))  # a department staff code joins that department only
    op.create_table(
        "department_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("aishe_id", sa.String(length=20), nullable=True),
        sa.Column("college_name", sa.String(length=300), nullable=False),
        sa.Column("branch", sa.String(length=120), server_default="", nullable=False),
        sa.Column("department_name", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=120), server_default="", nullable=False),
        sa.Column("state", sa.String(length=120), server_default="", nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=12), server_default="email", nullable=False),  # email | pending | approved | rejected
        sa.Column("campus_id", sa.Uuid(), nullable=True),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
    )
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobpilot_campus') THEN EXECUTE 'GRANT SELECT ON department_requests TO jobpilot_campus'; END IF;
        EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'grant skipped'; END $$;
    """)


def downgrade() -> None:
    op.drop_table("department_requests")
    op.drop_column("email_otps", "department_id")
    op.execute("DROP INDEX IF EXISTS ix_departments_staff_code")
    for c in ("plan_limit", "staff_code_expires_at", "staff_code_hash"):
        op.drop_column("departments", c)
    op.drop_column("campuses", "plan")

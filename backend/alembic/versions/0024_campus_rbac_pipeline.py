"""Campus placement portal: staff roles (TPO / HOD / Teacher) joining with a hashed staff code, department scope,
college-only jobs, the placement pipeline (AI match proposals staff approve, then rounds to placed), and pricing leads.

The placement pipeline holds student-level data, so it gets the same Postgres row-level security as profiles and
job_matches: inside an officer transaction only students who share their progress with the college are visible.

Revision ID: 5e1a7c3d9f68
Revises: 4d0f6b2c8e57
Create Date: 2026-11-12 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5e1a7c3d9f68"
down_revision: Union[str, Sequence[str], None] = "4d0f6b2c8e57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VISIBLE = (
    "COALESCE(current_setting('app.viewer_org', true), '') = '' OR user_id IN ("
    "SELECT m.user_id FROM org_members m JOIN consents c ON c.user_id = m.user_id "
    "WHERE m.org_id::text = current_setting('app.viewer_org', true) AND m.role = 'student' "
    "AND c.purpose = 'college_share' AND c.withdrawn_at IS NULL)"
)


def upgrade() -> None:
    op.add_column("organizations", sa.Column("domain", sa.String(length=120), nullable=True))
    op.add_column("organizations", sa.Column("staff_code_hash", sa.String(length=64), nullable=True))
    op.add_column("organizations", sa.Column("staff_code_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("org_members", sa.Column("department", sa.String(length=120), server_default="", nullable=False))
    # "officer" was the only staff role: it becomes the training & placement officer.
    op.execute("UPDATE org_members SET role = 'tpo' WHERE role = 'officer'")

    op.add_column("jobs", sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_jobs_org_id", "jobs", ["org_id"])

    op.create_table(
        "campus_placements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("drive_id", sa.Uuid(), sa.ForeignKey("campus_drives.id", ondelete="CASCADE"), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("stage", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("source", sa.String(length=24), server_default="ai_recommended", nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("reasoning", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("feedback", sa.Text(), server_default="", nullable=False),
        sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", "job_id", name="uq_placement_student_job"),
    )
    op.create_index("ix_placement_org_stage", "campus_placements", ["org_id", "stage"])
    op.execute("ALTER TABLE campus_placements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campus_placements FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY campus_placements_all ON campus_placements AS PERMISSIVE FOR ALL TO PUBLIC USING (true) WITH CHECK (true)")
    op.execute(f"CREATE POLICY campus_placements_campus_consent ON campus_placements AS RESTRICTIVE FOR SELECT TO PUBLIC USING ({VISIBLE})")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobpilot_officer') THEN
            EXECUTE 'GRANT SELECT ON campus_placements, organizations, org_members, jobs TO jobpilot_officer';
          END IF;
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'grant skipped';
        END $$;
        """
    )

    op.create_table(
        "campus_leads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("college", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=60), server_default="", nullable=False),
        sa.Column("students", sa.Integer(), nullable=True),
        sa.Column("plan", sa.String(length=30), server_default="", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("campus_leads")
    op.drop_table("campus_placements")
    op.drop_index("ix_jobs_org_id", table_name="jobs")
    op.drop_column("jobs", "org_id")
    op.execute("UPDATE org_members SET role = 'officer' WHERE role IN ('tpo', 'hod', 'teacher')")
    op.drop_column("org_members", "department")
    op.drop_column("organizations", "staff_code_set_at")
    op.drop_column("organizations", "staff_code_hash")
    op.drop_column("organizations", "domain")

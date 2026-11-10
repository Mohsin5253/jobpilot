"""Campus v2 (F11): row-level security for officer views, alumni, drive notifications; transparency_daily

Consent is enforced in Postgres: a RESTRICTIVE policy on profiles, job_matches and drive_statuses that only bites
when a transaction declares an officer context (app.viewer_org). Inside it, only students of that college with an
active college_share consent are visible. Outside it (every normal query) the policy is a no-op. FORCE makes it
apply to the table owner (the app's role on Render); officer queries also SET ROLE jobpilot_officer, a non-owner
role, so it applies even where the app connects as a superuser (CI, local).

Revision ID: f4c8a2e6b913
Revises: e7b1d9f2a684
Create Date: 2026-11-11 01:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f4c8a2e6b913'
down_revision: Union[str, Sequence[str], None] = 'e7b1d9f2a684'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("profiles", "job_matches", "drive_statuses")
VISIBLE = (
    "COALESCE(current_setting('app.viewer_org', true), '') = '' OR user_id IN ("
    "SELECT m.user_id FROM org_members m JOIN consents c ON c.user_id = m.user_id "
    "WHERE m.org_id::text = current_setting('app.viewer_org', true) AND m.role = 'student' "
    "AND c.purpose = 'college_share' AND c.withdrawn_at IS NULL)"
)


def upgrade() -> None:
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {t}_all ON {t} AS PERMISSIVE FOR ALL TO PUBLIC USING (true) WITH CHECK (true)")
        op.execute(f"CREATE POLICY {t}_campus_consent ON {t} AS RESTRICTIVE FOR SELECT TO PUBLIC USING ({VISIBLE})")
    # A read-only, non-owner role for officer queries. Creating roles needs CREATEROLE; where the database user
    # doesn't have it, FORCE above still applies the policy to the owner.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobpilot_officer') THEN
            CREATE ROLE jobpilot_officer NOLOGIN;
          END IF;
          EXECUTE 'GRANT USAGE ON SCHEMA public TO jobpilot_officer';
          EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO jobpilot_officer';
          EXECUTE format('GRANT jobpilot_officer TO %I', current_user);
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'jobpilot_officer role not created (no CREATEROLE); FORCE RLS still applies';
        END $$;
        """
    )
    op.create_table(
        'alumni',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('org_id', sa.Uuid(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('company', sa.String(length=200), nullable=False),
        sa.Column('company_key', sa.String(length=200), nullable=False, index=True),
        sa.Column('role', sa.String(length=200), server_default='', nullable=False),
        sa.Column('batch', sa.Integer(), nullable=True),
        sa.Column('contact', sa.String(length=320), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'transparency_daily',
        sa.Column('date', sa.Date(), primary_key=True),
        sa.Column('postings_verified', sa.Integer(), server_default='0', nullable=False),
        sa.Column('scams_flagged', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sends_approved', sa.Integer(), server_default='0', nullable=False),
        sa.Column('scam_checks', sa.Integer(), server_default='0', nullable=False),
        sa.Column('avg_cost_inr', sa.Float(), nullable=True),
    )
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('actor_user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('subject', sa.String(length=80), server_default='', nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.execute("DO $$ BEGIN EXECUTE 'GRANT SELECT ON alumni, transparency_daily TO jobpilot_officer'; EXCEPTION WHEN undefined_object OR insufficient_privilege THEN NULL; END $$;")


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('transparency_daily')
    op.drop_table('alumni')
    for t in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {t}_campus_consent ON {t}")
        op.execute(f"DROP POLICY IF EXISTS {t}_all ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")

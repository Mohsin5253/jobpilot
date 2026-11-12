"""Safety rails: payload-bound approval grants, the kill switch flag, voided drafts and reject reasons,
prompt-injection signals on postings, and database triggers that keep blocked postings out of matches and drafts

Revision ID: 8b4d0f6a3c95
Revises: 7a3c9e5f2b84
Create Date: 2026-11-13 10:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b4d0f6a3c95"
down_revision: Union[str, Sequence[str], None] = "7a3c9e5f2b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("outreach_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=20), server_default="web", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=40), nullable=True),
    )
    op.create_index("ix_grants_draft", "approval_grants", ["draft_id", "created_at"])
    op.create_index("ix_approval_grants_user_id", "approval_grants", ["user_id"])
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
    )
    op.add_column("outreach_drafts", sa.Column("void_reason", sa.String(length=200), nullable=True))
    op.add_column("outreach_drafts", sa.Column("reject_reason", sa.String(length=300), nullable=True))
    op.add_column("jobs", sa.Column("injection_signals", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))

    # Blocked ("suspicious") postings can't be matched, drafted or approved, whatever the application code does.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION jp_block_scam_match() RETURNS trigger AS $$
        BEGIN
          IF (SELECT legit_status FROM jobs WHERE id = NEW.job_id) = 'suspicious' THEN
            RAISE EXCEPTION 'posting % is blocked as a likely scam', NEW.job_id USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER jp_block_scam_match BEFORE INSERT ON job_matches FOR EACH ROW EXECUTE FUNCTION jp_block_scam_match();

        CREATE OR REPLACE FUNCTION jp_block_scam_draft() RETURNS trigger AS $$
        BEGIN
          IF NEW.status IN ('pending', 'approved', 'sent') AND (TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status) AND
             (SELECT j.legit_status FROM job_matches m JOIN jobs j ON j.id = m.job_id WHERE m.id = NEW.match_id) = 'suspicious' THEN
            RAISE EXCEPTION 'posting for draft % is blocked as a likely scam', NEW.id USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER jp_block_scam_draft BEFORE INSERT OR UPDATE OF status ON outreach_drafts FOR EACH ROW EXECUTE FUNCTION jp_block_scam_draft();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS jp_block_scam_draft ON outreach_drafts; DROP FUNCTION IF EXISTS jp_block_scam_draft();")
    op.execute("DROP TRIGGER IF EXISTS jp_block_scam_match ON job_matches; DROP FUNCTION IF EXISTS jp_block_scam_match();")
    op.drop_column("jobs", "injection_signals")
    op.drop_column("outreach_drafts", "reject_reason")
    op.drop_column("outreach_drafts", "void_reason")
    op.drop_table("system_flags")
    op.drop_table("approval_grants")

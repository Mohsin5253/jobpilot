import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db import Base

EMBED_DIM = settings.embedding_dim


class Stage(StrEnum):
    found = "found"
    shortlisted = "shortlisted"
    applied = "applied"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    archived = "archived"


class DraftStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    sent = "sent"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    resume_queued = "resume_queued"
    completed = "completed"
    failed = "failed"


def _now_col(**kw) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _now_col()
    # Bumped on password change / "sign out everywhere": tokens carry it, so older sessions stop working.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    plan: Mapped[str] = mapped_column(String(20), default="free", server_default="free")  # free | pro
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Demo visitors get a throwaway account that is deleted at expires_at.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    pro_interest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adult_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # age gate: said they're 18+
    inactivity_notice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # warned before the 12-month deletion
    daily_send_cap: Mapped[int] = mapped_column(Integer, default=5, server_default="5")  # quality quota, up to the plan max
    inbound_token: Mapped[str | None] = mapped_column(String(24), unique=True)  # alerts+<token>@INBOUND_EMAIL_DOMAIN
    language: Mapped[str] = mapped_column(String(5), default="en", server_default="en")  # en | hi | mr

    profile: Mapped["Profile | None"] = relationship(back_populates="user", uselist=False)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    resume_filename: Mapped[str | None] = mapped_column(String(300))
    resume_text: Mapped[str] = mapped_column(Text, default="")
    # Structured resume: see schemas.ResumeData
    resume: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Search preferences: see schemas.Preferences
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    # Researcher agent memory: {last_research_at, checked: [company slugs], added: [{provider, token, company, roles, at}]}
    research: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Proof-of-skills pack: {github: {...}, codeforces: {...}, items: [{kind, title, url, live}], verify_code}
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Campus: {college, branch, grad_year, cgpa, backlogs}
    academics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    proof_slug: Mapped[str | None] = mapped_column(String(40), unique=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))
    whatsapp_hour_local: Mapped[int] = mapped_column(Integer, default=8, server_default="8")  # IST hour for the digest
    whatsapp_last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="profile")


class Job(Base):
    """A posting. Jobs are global and de-duplicated by (source, external_id) so users share fetches."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external"),
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(200), default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    recruiter_email: Mapped[str | None] = mapped_column(String(320))
    company_domain: Mapped[str | None] = mapped_column(String(255), index=True)  # resolved by the Contact Finder
    # Where the posting is listed (LinkedIn, Indeed, Naukri, Glassdoor, Wellfound, company site...) and every
    # apply link we know for it: [{publisher, url, direct}].
    publisher: Mapped[str | None] = mapped_column(String(80))
    apply_links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    # Authenticity check of the apply link: ok | unverified (site blocks checks) | dead
    link_status: Mapped[str | None] = mapped_column(String(20))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # company + title + city, normalised: the same role listed on several boards is stored once
    dedupe_key: Mapped[str | None] = mapped_column(String(300), index=True)
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list)
    track: Mapped[str] = mapped_column(String(20), default="technical")  # technical | non_technical
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = _now_col()
    # Refreshed every time a source still lists the posting; stale = closed / filled.
    last_seen_at: Mapped[datetime] = _now_col(index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    # The source tagged it internship / entry level (e.g. The Muse "Internship" level) even if the title doesn't say so.
    entry_level: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Ghost-job risk: low | medium | high, with the reasons (old but still listed, reposted, unverifiable...)
    ghost_risk: Mapped[str] = mapped_column(String(10), default="low", server_default="low")
    ghost_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # The Verifier's verdict: verified | caution | suspicious (None until checked), with its reasons.
    legit_status: Mapped[str | None] = mapped_column(String(12))
    legit_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    legit_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Verifier v2: the latest verification row (checks with evidence), how often the role was reposted, and a
    # 0-100 ghost-job score (age, reposts, last seen, whether the ATS still lists it, career-page presence).
    verification_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("verifications.id", ondelete="SET NULL", use_alter=True))
    repost_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ghost_score: Mapped[int | None] = mapped_column(Integer)


class Verification(Base):
    """One Scam Shield / Verifier verdict. Public checks keep only each check's status (no quoted evidence) and a hash
    of the input, so nothing a student pasted is stored; pipeline checks of public postings keep their evidence."""

    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="public", server_default="public")  # public | pipeline
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    verdict: Mapped[str] = mapped_column(String(20))  # Likely safe | Suspicious | Likely scam
    score: Mapped[int] = mapped_column(Integer)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    ghost_score: Mapped[int | None] = mapped_column(Integer)
    llm_category: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = _now_col(index=True)


class ScamReport(Base):
    """Opt-in "report this scam": a redacted copy (no phone numbers, email users, IDs) for moderation and stats."""

    __tablename__ = "scam_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id", ondelete="CASCADE"))
    redacted_text: Mapped[str] = mapped_column(Text)
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new")  # new | confirmed | dismissed
    created_at: Mapped[datetime] = _now_col()


class JobMatch(Base):
    """One user's view of one job: fit score, explanation and where it sits on the Kanban board."""

    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_match_user_job"),
        Index("ix_match_user_stage", "user_id", "stage"),
        Index("ix_match_user_score", "user_id", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    score: Mapped[float] = mapped_column(Float, default=0)
    semantic_score: Mapped[float] = mapped_column(Float, default=0)
    skill_score: Mapped[float] = mapped_column(Float, default=0)
    llm_score: Mapped[float | None] = mapped_column(Float)
    strengths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSONB, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(20), default=Stage.found)
    stage_changed_at: Mapped[datetime] = _now_col()
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    user_rating: Mapped[int | None] = mapped_column(Integer)  # 1-5, feeds the match eval set
    # What happened: none | no_reply | replied | interview | offer | rejected (the feedback loop)
    outcome: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    resume_variant: Mapped[str] = mapped_column(String(2), default="A", server_default="A")  # A skills-first, B projects-first
    ppo_status: Mapped[str] = mapped_column(String(20), default="none", server_default="none")  # none | eligible | offered | converted
    created_at: Mapped[datetime] = _now_col()

    job: Mapped[Job] = relationship(lazy="joined")
    tailored: Mapped["TailoredResume | None"] = relationship(back_populates="match", uselist=False)
    drafts: Mapped[list["OutreachDraft"]] = relationship(back_populates="match", order_by="OutreachDraft.created_at")


class TailoredResume(Base):
    __tablename__ = "tailored_resumes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_matches.id", ondelete="CASCADE"), unique=True)
    # [{source_id, original, rewritten, keywords, reverted}]
    bullets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # {passed, violations: [{bullet, terms, numbers}]}
    guard_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = _now_col()

    match: Mapped[JobMatch] = relationship(back_populates="tailored")


class OutreachDraft(Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (Index("ix_draft_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_matches.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    linkedin_note: Mapped[str] = mapped_column(Text, default="")
    to_email: Mapped[str | None] = mapped_column(String(320))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("company_contacts.id", ondelete="SET NULL"))
    cc_email: Mapped[str | None] = mapped_column(String(320))  # the company's official hiring inbox, when To is a person
    kind: Mapped[str] = mapped_column(String(20), default="application", server_default="application")  # application | referral
    status: Mapped[str] = mapped_column(String(20), default=DraftStatus.pending)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_worthiness: Mapped[int | None] = mapped_column(Integer)  # 0-100, recorded when approved
    approval_channel: Mapped[str | None] = mapped_column(String(20))  # web | whatsapp
    created_at: Mapped[datetime] = _now_col()

    match: Mapped[JobMatch] = relationship(back_populates="drafts")
    contact: Mapped["CompanyContact | None"] = relationship(lazy="joined")


class ProofLink(Base):
    """A signed, per-application proof page (/p/{slug}/{token}). The payload is Ed25519-signed so a recruiter can
    confirm it at /api/v1/verify/{token}; the student can revoke it; views are logged server-side, never by pixels."""

    __tablename__ = "proof_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_drafts.id", ondelete="CASCADE"), unique=True)
    slug: Mapped[str] = mapped_column(String(40))
    token: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signature: Mapped[str] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    views_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class ProofLinkView(Base):
    __tablename__ = "proof_link_views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    proof_link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proof_links.id", ondelete="CASCADE"), index=True)
    viewed_at: Mapped[datetime] = _now_col()
    ua_family: Mapped[str] = mapped_column(String(30), default="other", server_default="other")  # chrome | safari | ... | bot


class WhatsAppEvent(Base):
    """Message ids already handled: Meta retries webhooks, and an approval must never run twice."""

    __tablename__ = "whatsapp_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    received_at: Mapped[datetime] = _now_col()


class Quota(Base):
    """Approved sends per user per day (IST), against the cap in force that day."""

    __tablename__ = "quotas"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    sends_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cap: Mapped[int] = mapped_column(Integer)


class ApprovalEvent(Base):
    """Audit log: every approve / reject / send, from which channel. The IP is stored only as a salted hash."""

    __tablename__ = "approval_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("outreach_drafts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # approve | reject | send
    channel: Mapped[str] = mapped_column(String(20), default="web", server_default="web")  # web | whatsapp
    ip_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = _now_col()


class AgentRun(Base):
    """One pipeline execution. Doubles as the work queue row (claimed with SKIP LOCKED)."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_runs_user_created", "user_id", "created_at"),
        Index("ix_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(30), default=RunStatus.queued)
    current_step: Mapped[str | None] = mapped_column(String(40))
    # [{agent, status, started_at, ended_at, detail}]
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Inputs for special runs, e.g. {"rescore_match_ids": [...]} after you answer skill questions.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Numeric(14, 8), default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class LLMCall(Base):
    """Every model call, for per-agent cost / latency dashboards."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(14, 8), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now_col()


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        UniqueConstraint("match_id", "kind", name="uq_reminder_match_kind"),
        Index("ix_reminder_user_due", "user_id", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_matches.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), default="follow_up")
    message: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class QuestionStatus(StrEnum):
    open = "open"
    yes = "yes"
    no = "no"
    dismissed = "dismissed"


class SkillQuestion(Base):
    """A gap the Interviewer agent asks you about. Asked once per skill; a "yes" with details adds
    the skill (in your own words) to your profile, so the Tailor may use it without fabricating."""

    __tablename__ = "skill_questions"
    __table_args__ = (
        UniqueConstraint("user_id", "skill", name="uq_question_user_skill"),
        Index("ix_question_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    skill: Mapped[str] = mapped_column(String(80))
    question: Mapped[str] = mapped_column(Text)
    # Match ids that miss mainly because of this skill (what a "yes" could unlock).
    match_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default=QuestionStatus.open)
    answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now_col()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """In-app alerts: a new job that fits you opened, the Researcher found new companies, etc."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))  # new_match | research | skills
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_matches.id", ondelete="CASCADE"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class CompanyContact(Base):
    """A real, publicly sourced contact at a company. Every row says where it came from:
    the job posting, the company's own website, or Hunter.io (only addresses Hunter *found* on public
    pages, never pattern-guessed ones), with the pages it appears on."""

    __tablename__ = "company_contacts"
    __table_args__ = (UniqueConstraint("domain", "email", name="uq_contact_domain_email"), Index("ix_contact_domain", "domain"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320))
    kind: Mapped[str] = mapped_column(String(20), default="person")  # person | generic
    first_name: Mapped[str] = mapped_column(String(100), default="")
    last_name: Mapped[str] = mapped_column(String(100), default="")
    position: Mapped[str] = mapped_column(String(200), default="")
    seniority: Mapped[str] = mapped_column(String(20), default="")  # junior | senior | executive
    department: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(20))  # posting | website | hunter
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    verification: Mapped[str] = mapped_column(String(20), default="")  # valid | accept_all | unknown | ""
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # [{uri, last_seen_on}]
    linkedin: Mapped[str | None] = mapped_column(String(300))
    fetched_at: Mapped[datetime] = _now_col()


class SourceRegistry(Base):
    """Every place jobs can come from, with its terms-of-service notes and rate limit. `enabled=false` rows
    document what we never automate (LinkedIn, Internshala, Naukri, Unstop, ...). Admins can switch a source off."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # ats_api | career_page | github_repo | public_api | licensed_api | deep_link | user_forwarded | user_pasted | blocked
    base_url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    tos_notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SourceTarget(Base):
    """One thing the shared ingester fetches: a company board (greenhouse/stripe), a public feed, or an
    aggregator search (adzuna/"data analyst intern"). Fetched once for every user who wants it; `demand`
    is how many active users want it, and `fetch_prefs` is the widest filter any of them needs."""

    __tablename__ = "source_targets"
    __table_args__ = (UniqueConstraint("source", "target", name="uq_source_target"), Index("ix_source_targets_due", "next_due_at"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30))
    target: Mapped[str] = mapped_column(String(300))  # board token, query, or "*" (a quota source's budget clock)
    demand: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fetch_prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    next_due_at: Mapped[datetime] = _now_col()
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(300), default="", server_default="")
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    postings: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class BoardProbe(Base):
    """The Researcher's shared memory: whether a company slug has a public careers board, so a company
    checked for one user isn't probed again for the next."""

    __tablename__ = "board_probes"

    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {provider, token, roles} or null (no board)
    checked_at: Mapped[datetime] = _now_col()


class RateLimit(Base):
    """Fixed-window counters shared by every API replica."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class PasswordReset(Base):
    __tablename__ = "password_resets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the emailed token
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class MailAccount(Base):
    """The user's own outgoing mail (e.g. Gmail with an app password). Applications are sent from their
    address, never from a shared one. The password is encrypted at rest and never returned by the API."""

    __tablename__ = "mail_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=587)
    username: Mapped[str] = mapped_column(String(320))
    from_email: Mapped[str] = mapped_column(String(320))
    from_name: Mapped[str] = mapped_column(String(200), default="")
    password_enc: Mapped[str | None] = mapped_column(Text)  # SMTP app password (legacy); None for Gmail OAuth
    # smtp (app password) | gmail_oauth (Google sign-in, gmail.send scope only: the refresh token, encrypted)
    provider: Mapped[str] = mapped_column(String(20), default="smtp", server_default="smtp")
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # sends are spaced >= 90 s apart
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())


class Consent(Base):
    """DPDP-style consent log: one row per purpose the user agreed to, withdrawn rows kept for the record."""

    __tablename__ = "consents"
    __table_args__ = (Index("ix_consent_user_purpose", "user_id", "purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(30))  # see services/consent.PURPOSES
    notice_version: Mapped[str] = mapped_column(String(20))  # the notice the user saw when agreeing
    method: Mapped[str] = mapped_column(String(30), default="checkbox", server_default="checkbox")  # checkbox | google_oauth | whatsapp | migrated ...
    guardian_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # verifiable parental consent
    granted_at: Mapped[datetime] = _now_col()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RightsRequest(Base):
    """A data-principal request under the DPDP Act (access, correction, erasure, grievance, nomination), answered
    within 30 days. Grievances can also come from people without an account (user_id None, contact_email set)."""

    __tablename__ = "rights_requests"
    __table_args__ = (Index("ix_rights_status_due", "status", "due_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contact_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(20))
    details: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")  # open | resolved
    response: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = _now_col()
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    """Personal tokens for the Chrome extension: stored hashed, scoped to /api/extension, revocable."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="Chrome extension")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class Organization(Base):
    """A college (placement cell). Students join with the invite code."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    invite_code: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = _now_col()


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (UniqueConstraint("user_id", name="uq_org_member_user"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="student")  # student | officer
    joined_at: Mapped[datetime] = _now_col()


class CampusDrive(Base):
    """An on-campus placement / internship drive: posted by the college (org_id) or tracked by a student (user_id)."""

    __tablename__ = "campus_drives"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="internship")  # internship | full_time
    compensation: Mapped[str] = mapped_column(String(100), default="")
    # {min_cgpa, branches: [..], max_backlogs, grad_years: [..]}
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    register_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rounds: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")  # [{name, type, date}]
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now_col()


class DriveStatus(Base):
    """One student's progress in a drive."""

    __tablename__ = "drive_statuses"
    __table_args__ = (UniqueConstraint("drive_id", "user_id", name="uq_drive_user"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    drive_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campus_drives.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="interested")  # interested | registered | in_rounds | selected | rejected | skipped
    round_index: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())

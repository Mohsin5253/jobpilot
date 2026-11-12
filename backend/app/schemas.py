import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------- Resume ----------


class ExperienceItem(BaseModel):
    title: str = ""
    organization: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list, description="The role's tech stack, when the resume lists one")


class ProjectItem(BaseModel):
    name: str = ""
    tech: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    school: str = ""
    degree: str = ""
    start: str = ""
    end: str = ""
    details: str = ""


class SkillGroup(BaseModel):
    """A labelled skills line, e.g. "Languages: Java, Python"."""

    name: str = ""
    items: list[str] = Field(default_factory=list)


class AdditionalSkill(BaseModel):
    """A skill you confirmed to the Interviewer agent, described in your own words."""

    skill: str = ""
    details: str = ""


class ResumeData(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list, description="Skills as the resume groups them (Languages, Tools…)")
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list, description="Certifications, awards, achievements and positions, one per line")
    additional: list[AdditionalSkill] = Field(default_factory=list)

    def bullet_index(self) -> list[tuple[str, str]]:
        """Stable ids for every bullet so the Tailor can cite which source line it rephrased."""
        out: list[tuple[str, str]] = []
        for i, e in enumerate(self.experience):
            out += [(f"exp{i}.b{j}", b) for j, b in enumerate(e.bullets)]
        for i, p in enumerate(self.projects):
            out += [(f"proj{i}.b{j}", b) for j, b in enumerate(p.bullets)]
        out += [(f"add{i}", a.details) for i, a in enumerate(self.additional) if a.details.strip()]
        return out

    def embedding_text(self) -> str:
        parts = [self.summary, "Skills: " + ", ".join(self.skills)]
        parts += [f"{e.title} at {e.organization}. " + " ".join(e.bullets) + (f" Tech: {', '.join(e.tech)}." if e.tech else "") for e in self.experience]
        parts += [f"Project {p.name} ({', '.join(p.tech)}). " + " ".join(p.bullets) for p in self.projects]
        parts += [f"{a.skill}: {a.details}" for a in self.additional]
        parts += self.certifications
        return "\n".join(p for p in parts if p.strip())


# Real company career boards with roles in India (verified live). Used as defaults so a new account
# gets real postings on its first run; edit them in Settings.
DEFAULT_GREENHOUSE = ["stripe", "databricks", "mongodb", "inmobi", "rubrik", "hackerrank", "druva", "groww", "gitlab", "twilio", "elastic"]
DEFAULT_LEVER = ["paytm", "meesho", "zeta", "mindtickle", "cred"]
DEFAULT_ASHBY = ["sarvam", "notion"]


def _boards(defaults: list[str]):
    def factory() -> list[str]:
        from app.config import settings

        return list(defaults) if settings.seed_company_boards else []

    return factory


Track = Literal["technical", "non_technical"]


class Preferences(BaseModel):
    # Optional focus: when set, a posting must mention one of these (all words of it). Empty = no filter.
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["India", "Remote"])
    tracks: list[Track] = Field(default_factory=lambda: ["technical", "non_technical"])
    internships_only: bool = True  # internships, trainee, graduate / new-grad and entry-level roles
    remote_ok: bool = True
    max_age_days: int = Field(default=45, ge=1, le=365)  # skip postings older than this (when the date is known)
    min_score: int = Field(default=60, ge=0, le=100)
    # The ATS score a tailored resume must reach for its job before it's sent (0 = no gate).
    ats_target: int = Field(default=0, ge=0, le=100)
    # Words speech-to-text should always spell right (names, places, tools), added by the student.
    speech_words: list[str] = Field(default_factory=list, max_length=100)
    greenhouse_boards: list[str] = Field(default_factory=_boards(DEFAULT_GREENHOUSE))
    lever_boards: list[str] = Field(default_factory=_boards(DEFAULT_LEVER))
    ashby_boards: list[str] = Field(default_factory=_boards(DEFAULT_ASHBY))
    public_job_feeds: bool = True  # The Muse, Remotive, Jobicy, GitHub internship lists
    career_pages: list[str] = Field(default_factory=list, max_length=20)  # company careers pages to watch (JSON-LD only)
    adzuna_country: str = "in"
    daily_run_hour_utc: int = Field(default=3, ge=0, le=23)
    daily_runs_enabled: bool = True
    research_enabled: bool = True  # Researcher keeps discovering companies + re-running the agents
    research_interval_hours: int = Field(default=6, ge=2, le=48)
    refresh_minutes: int = Field(default=1, ge=1, le=60)  # how often to check job sources for new postings
    email_alerts: bool = False  # email me new matches (needs SMTP configured)
    max_jobs_per_source: int = Field(default=60, ge=5, le=300)
    weekly_application_cap: int = Field(default=10, ge=3, le=30)  # quality over volume: tailored applications a week


# ---------- Auth ----------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=200)
    consent: bool = False  # the privacy notice, explicitly accepted (DPDP)
    adult: bool = False  # age gate: "I am 18 or older"


class LoginIn(BaseModel):
    email: str = Field(max_length=320)  # not EmailStr: a login form should answer "wrong credentials", not lint the address
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    name: str
    created_at: datetime
    plan: str = "free"
    is_demo: bool = False
    is_admin: bool = False
    expires_at: datetime | None = None
    adult_confirmed_at: datetime | None = None
    language: str = "en"


class ForgotPasswordIn(BaseModel):
    email: str = Field(max_length=320)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class MailAccountIn(BaseModel):
    host: str = Field(default="smtp.gmail.com", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: EmailStr
    password: str = Field(min_length=4, max_length=200)  # e.g. a 16-character Gmail app password
    from_name: str = Field(default="", max_length=200)


class MailAccountOut(BaseModel):
    connected: bool
    provider: str | None = None  # smtp | gmail_oauth
    google_available: bool = False  # Google sign-in for sending is configured on this server
    host: str | None = None
    port: int | None = None
    from_email: str | None = None
    from_name: str | None = None
    verified_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Profile ----------


class ProfileOut(BaseModel):
    resume_filename: str | None
    resume: ResumeData
    preferences: Preferences
    has_resume: bool
    updated_at: datetime | None


class ProfileUpdate(BaseModel):
    resume: ResumeData | None = None
    preferences: Preferences | None = None


# ---------- Jobs / matches ----------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    company: str
    title: str
    location: str
    remote: bool
    url: str
    description: str
    salary_min: float | None
    salary_max: float | None
    recruiter_email: str | None
    skills: list[str]
    track: str
    posted_at: datetime | None
    last_seen_at: datetime
    publisher: str | None = None
    apply_links: list[dict] = Field(default_factory=list)
    link_status: str | None = None
    verified_at: datetime | None = None
    ghost_risk: str = "low"
    ghost_reasons: list[str] = Field(default_factory=list)
    legit_status: str | None = None
    legit_reasons: list[str] = Field(default_factory=list)


class TailoredBullet(BaseModel):
    source_id: str
    original: str
    rewritten: str
    keywords: list[str] = Field(default_factory=list)
    reverted: bool = False
    # You declined this rewrite in the reviewer: your original wording goes on the resume.
    declined: bool = False


class BulletDecision(BaseModel):
    declined: bool


class TailoredOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bullets: list[TailoredBullet]
    guard_report: dict
    model: str
    created_at: datetime


class ContactSource(BaseModel):
    uri: str
    last_seen_on: str | None = None


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    domain: str
    email: str
    kind: str
    first_name: str
    last_name: str
    position: str
    seniority: str
    department: str
    source: str
    confidence: int
    verification: str
    sources: list[ContactSource]
    linkedin: str | None


class ContactsOut(BaseModel):
    domain: str | None
    hunter_enabled: bool
    contacts: list[ContactOut]


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    match_id: uuid.UUID
    kind: str = "application"  # application | referral
    run_id: uuid.UUID | None
    subject: str
    email_body: str
    linkedin_note: str
    to_email: str | None
    contact_id: uuid.UUID | None = None
    contact: ContactOut | None = None
    cc_email: str | None = None
    status: str
    decided_at: datetime | None
    sent_at: datetime | None
    created_at: datetime


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job: JobOut
    score: float
    semantic_score: float
    skill_score: float
    llm_score: float | None
    strengths: list[str]
    gaps: list[str]
    explanation: str
    stage: str
    stage_changed_at: datetime
    applied_at: datetime | None
    follow_up_at: datetime | None
    notes: str
    user_rating: int | None
    created_at: datetime
    outcome: str = "none"
    outcome_at: datetime | None = None
    rejection_reason: str = ""
    resume_variant: str = "A"
    ppo_status: str = "none"
    has_tailored: bool = False
    pending_draft: bool = False
    approved_draft: bool = False
    sent_draft: bool = False
    proof_views: int = 0  # opens of this application's signed Proof Link
    proof_last_viewed_at: datetime | None = None


class MatchDetail(MatchOut):
    tailored: TailoredOut | None = None
    drafts: list[DraftOut] = Field(default_factory=list)


class MatchPage(BaseModel):
    items: list[MatchOut]
    total: int


Outcome = Literal["none", "no_reply", "replied", "interview", "offer", "rejected"]


class MatchUpdate(BaseModel):
    stage: Literal["found", "shortlisted", "applied", "interview", "offer", "rejected", "archived"] | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    user_rating: int | None = Field(default=None, ge=1, le=5)
    outcome: Outcome | None = None
    rejection_reason: str | None = Field(default=None, max_length=300)
    ppo_status: Literal["none", "eligible", "offered", "converted"] | None = None
    # Evidence for an interview (e.g. "calendar invite from hr@acme.com on 12 Nov"): needed for the outcome plan.
    interview_evidence: str | None = Field(default=None, max_length=500)


class DraftEdit(BaseModel):
    to_email: str | None = Field(default=None, max_length=320)
    contact_id: uuid.UUID | None = None  # pick one of the job's real contacts as the recipient
    cc_email: str | None = Field(default=None, max_length=320)  # "" removes the CC
    subject: str | None = Field(default=None, max_length=300)
    email_body: str | None = Field(default=None, max_length=5000)
    linkedin_note: str | None = Field(default=None, max_length=600)


class DraftDecision(DraftEdit):
    decision: Literal["approve", "reject"]


class DraftWithJob(DraftOut):
    company: str
    title: str
    score: float
    job_url: str
    job_source: str
    recruiter_email: str | None
    legit_status: str | None = None  # verified | caution | suspicious (Verifier v2)
    legit_reasons: list[str] = []
    ghost_score: int | None = None
    send_worthiness: int | None = None  # 0-100, shown before approval (F5)
    worthiness_parts: dict[str, int] = {}


# ---------- Runs ----------


class RunStep(BaseModel):
    agent: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    detail: str = ""


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    trigger: str
    status: str
    current_step: str | None
    steps: list[RunStep]
    stats: dict
    error: str | None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    llm_calls: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime



class LLMCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    attempts: int
    success: bool
    error: str | None
    created_at: datetime


class RunDetail(RunOut):
    calls: list[LLMCallOut] = Field(default_factory=list)


# ---------- Stats / reminders ----------


class AgentCost(BaseModel):
    agent: str
    calls: int
    cost_usd: float
    avg_latency_ms: float
    input_tokens: int
    output_tokens: int


class DailyPoint(BaseModel):
    day: str
    found: int
    applied: int
    cost_usd: float


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    title: str
    body: str
    match_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class ResearchState(BaseModel):
    last_research_at: datetime | None = None
    checked: int = 0
    added: list[dict] = Field(default_factory=list)
    next_run_at: datetime | None = None


class Overview(BaseModel):
    stage_counts: dict[str, int]
    total_matches: int
    strong_matches: int
    avg_score: float
    pending_approvals: int
    open_questions: int
    unread_notifications: int
    due_reminders: int
    response_rate: float
    cost_30d: float
    runs_30d: int
    avg_run_latency_ms: float
    agent_costs: list[AgentCost]
    daily: list[DailyPoint]
    last_run: RunOut | None
    llm_mode: str  # "groq" | "anthropic" | "offline"
    llm_models: list[str]


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    match_id: uuid.UUID
    kind: str
    message: str
    due_at: datetime
    company: str = ""
    title: str = ""


# ---------- Skill questions ----------


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    skill: str
    question: str
    status: str
    answer: str
    unlocks: int = 0
    jobs: list[str] = Field(default_factory=list)  # "Title @ Company" of jobs this would help
    created_at: datetime


class Answer(BaseModel):
    id: uuid.UUID
    has_skill: bool
    details: str = Field(default="", max_length=2000)


class AnswersIn(BaseModel):
    answers: list[Answer] = Field(min_length=1, max_length=50)


class AnswersOut(BaseModel):
    answered: int
    skills_added: list[str]
    rematch_run_id: uuid.UUID | None
    rechecking_jobs: int

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# USD per million tokens: (input, output). Cache reads are billed at 10% of input.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "qwen/qwen3.8-27b": (0.80, 4.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}

# (fast model for scoring / parsing, smart model for writing) per provider
PROVIDER_MODELS: dict[str, tuple[str, str]] = {
    "groq": ("openai/gpt-oss-20b", "openai/gpt-oss-120b"),
    "anthropic": ("claude-haiku-5-5", "claude-opus-5-5"),
}


DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production-please"

# Per-plan daily limits. Free is generous enough to land internships; Pro is for heavy applying.
PLAN_LIMITS: dict[str, dict[str, float]] = {
    "free": {"sends_per_day_max": 10, "drafts_per_day": 10, "manual_runs_per_day": 3, "min_refresh_minutes": 15, "llm_usd_per_day": 0.05},
    "pro": {"sends_per_day_max": 50, "drafts_per_day": 50, "manual_runs_per_day": 20, "min_refresh_minutes": 1, "llm_usd_per_day": 0.50},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://localhost/jobpilot"
    # Per process. Budget: (API processes + workers) x (pool + overflow) must stay under Postgres max_connections.
    db_pool_size: int = 5
    db_max_overflow: int = 10

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_ttl_hours: int = 24 * 7
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]  # comma-separated in env
    app_url: str = "http://localhost:3000"  # public web origin, used in password-reset links
    # Fernet key that encrypts users' mail passwords at rest. Generate one with
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Dev / tests derive one from the JWT secret; prod refuses to start without a real one.
    encryption_key: str | None = None
    admin_emails: Annotated[list[str], NoDecode] = []  # comma-separated; these accounts can open /admin
    sentry_dsn: str | None = None
    rate_limits_enabled: bool = True
    # Rupees per US dollar, for showing AI cost (billed in USD) in ₹ on the landing page. Not a price.
    usd_inr_rate: float = 88.0
    consent_version: str = "2026-11-b"  # bump when the privacy notice changes; users re-confirm ("-b": campus college records vs JobPilot data)
    extension_origin_regex: str = r"chrome-extension://[a-p]{32}"  # the Chrome autofill extension calls the API directly

    # Proof-of-skills pack (official public APIs). A token raises GitHub's limit from 60 to 5,000 requests / hour.
    github_token: str | None = None
    evidence_cache_hours: int = 24

    # Quality gate: at most this many tailored applications a week (per-user preference, capped by plan).
    default_weekly_application_cap: int = 10

    # Razorpay (UPI, cards). Payments stay off until the keys are set; Pro can still be switched on by hand in /admin.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_pro_plan_id: str | None = None  # a ₹299/month plan created in the Razorpay dashboard (must match price_pro_inr)
    price_pro_inr: int = 299
    price_week_pass_inr: int = 79
    price_year_pass_inr: int = 2499  # Year Pass: 365 days of Pro, paid once, nothing renews (about 30% off monthly)
    price_outcome_inr: int = 99
    outcome_plan_enabled: bool = False  # experimental "₹99 on first interview": off until confirmed
    # Seller details printed on invoices. With a GSTIN, invoices show 18% GST (CGST+SGST within the state, IGST
    # otherwise); without one they're receipts that say no GST was charged.
    seller_name: str = "JobPilot"
    seller_address: str = ""
    seller_gstin: str | None = None
    seller_state_code: str = "27"  # GST state code (27 = Maharashtra)
    # Ed25519 seed (32 bytes, base64url) that signs Proof Links. Optional: derived from ENCRYPTION_KEY when unset.
    proof_signing_key: str | None = None
    # Gmail sending through Google OAuth (scope gmail.send only). Off until both are set; the redirect URI to register
    # in Google Cloud is {APP_URL}/api/mail/google/callback.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Scam Shield (public): fetch pasted links (public hosts only), look up domain age over RDAP, and cap the AI
    # second opinions per day across all anonymous checks.
    scam_fetch_urls: bool = True
    scam_rdap_enabled: bool = True
    scam_llm_daily_cap: int = 300
    send_spacing_s: int = 90  # minimum gap between two sends from one mailbox
    # Safety rails (app/safety): an approval covers one exact email for this long; KILL_SWITCH stops every outside
    # effect (sends, WhatsApp, publishing) at once; Hunter contacts below this confidence are never used.
    approval_grant_ttl_min: int = 30
    kill_switch: bool = False
    hunter_min_confidence: int = 80
    # Outbound requests: the per-source ceilings from the sources table, shared across replicas through Postgres.
    egress_throttle_enabled: bool = True
    egress_max_wait_s: float = 65.0
    inactive_delete_days: int = 365  # DPDP retention: accounts unused this long are deleted...
    inactive_notice_days: int = 30  # ...after a notice this many days earlier

    # WhatsApp daily digest (official WhatsApp Cloud API). Off until all of these are set.
    whatsapp_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_template: str = "jobpilot_daily_digest"  # an approved template with 2 body params: name, summary
    whatsapp_template_lang: str = "en"
    whatsapp_app_secret: str | None = None  # verifies webhook signatures
    # Approval template: 3 body params (role, company, send-worthiness) and quick-reply buttons Approve / Edit in app / Skip.
    # Off (digest only) until it's approved in WhatsApp Manager and named here.
    whatsapp_approval_template: str | None = None
    whatsapp_template_langs: Annotated[list[str], NoDecode] = ["en"]  # languages both templates are approved in (en, hi, mr)
    whatsapp_verify_token: str | None = None  # webhook subscription handshake

    # LLM: "auto" uses the provider when its API key is set, otherwise the deterministic offline agents.
    llm_provider: Literal["groq", "anthropic"] = "groq"
    llm_mode: Literal["auto", "on", "offline"] = "auto"
    groq_api_key: str | None = None
    # Speech-to-text for spoken interview answers: the full large-v3 is the most accurate; whisper-large-v3-turbo is faster/cheaper.
    stt_model: str = "whisper-large-v3-turbo"  # fastest; with the speaker's vocabulary as accurate as large-v3 in our tests
    stt_timeout_s: float = 6.0  # then the fallback model (large-v3) is tried once
    stt_ai_budget_ms: int = 600  # the AI spelling pass is skipped if it takes longer (Flow's latency budget)
    # Polished mode: the clean-up model (a fast instruct model; reasoning off) and its time budget.
    stt_cleanup_model: str = "qwen/qwen3.8-27b"
    stt_cleanup_reasoning: str = "none"  # Groq reasoning_effort for models that think by default; "" to omit
    stt_cleanup_fallback_model: str = "openai/gpt-oss-20b"  # used while the first is rate-limited
    stt_cleanup_fallback_reasoning: str = "low"
    stt_cleanup_budget_ms: int = 600
    anthropic_api_key: str | None = None
    fast_model: str = ""  # scoring / parsing; empty = provider default (PROVIDER_MODELS)
    smart_model: str = ""  # writing (tailor + outreach); empty = provider default
    smart_fallbacks: bool = True  # Anthropic only: server-side refusal fallbacks on the smart model
    llm_concurrency: int = 2  # Groq's free tier allows ~8k tokens/min on gpt-oss-120b
    llm_rate_limit_wait_s: float = 90.0  # total time one call may spend waiting out 429s
    llm_max_repairs: int = 2

    embedding_backend: Literal["fastembed", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    hunter_api_key: str | None = None  # Hunter.io: senior people at a company, with public sources
    website_contacts_enabled: bool = True  # read hiring addresses from companies' own careers/contact pages
    contacts_cache_days: int = 30
    # JSearch (Google for Jobs index: LinkedIn, Indeed, Glassdoor, Naukri, Wellfound, company sites...).
    # Either an OpenWeb Ninja key or a RapidAPI key; the free plan is ~200 requests a month.
    jsearch_api_key: str | None = None
    jsearch_provider: Literal["rapidapi", "openwebninja"] = "rapidapi"
    jsearch_monthly_requests: int = 200
    verify_links: bool = True  # check that apply links are live before showing a job
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    adzuna_monthly_requests: int = 1000  # free developer keys; raise it if Adzuna gives you more
    demo_source: bool = False  # bundled sample postings (fictional companies) for offline demos / tests
    seed_company_boards: bool = True  # new accounts start with a curated list of real company boards
    public_feeds_enabled: bool = True  # The Muse / Remotive / Jobicy (no key needed)
    # Community internship lists on GitHub (public JSON). Comma-separated; empty turns the source off.
    github_listings_urls: Annotated[list[str], NoDecode] = ["https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json"]
    # Forwarded job-alert emails: an inbound-mail provider posts them to /api/inbound/email?secret=...
    inbound_email_domain: str | None = None  # e.g. alerts.yourdomain.in -> alerts+<token>@alerts.yourdomain.in
    inbound_email_secret: str | None = None
    source_timeout_s: float = 20.0
    source_cache_s: float = 90.0  # every user polling the same board within this window shares one fetch

    # Pipeline knobs
    llm_score_top_k: int = 25  # only the top-K by vector similarity get an LLM fit review
    tailor_top_n: int = 5
    researcher_enabled: bool = True  # master switch for the Researcher agent (off in tests: it calls live board APIs)
    research_cooldown_hours: int = 20  # LLM company discovery at most this often per user
    research_max_candidates: int = 40  # companies probed per discovery pass
    near_miss_band: int = 20  # jobs this far below your min score trigger skill questions
    max_questions_per_run: int = 5
    follow_up_days: int = 7

    # Shared ingestion: every board / feed / search is fetched once for all users who want it.
    ingest_max_targets_per_tick: int = 120  # per worker per minute; more replicas = more throughput
    ingest_concurrency: int = 16
    fanout_min_semantic: float = 15.0  # a new job wakes a user's agents if it's at least this close to their resume (0-100)
    scout_candidates: int = 200  # jobs from the shared index the Scout hands the Matcher per run

    # Demo mode (one-click "Try the demo" on the landing page)
    demo_enabled: bool = True
    demo_ttl_hours: int = 24
    demo_template_email: str = "demo@example.com"  # the showcase account every demo visitor gets a copy of

    # Retention (daily sweep)
    retain_llm_calls_days: int = 90
    retain_notifications_days: int = 60
    retain_unmatched_jobs_days: int = 60

    # Worker
    embedded_worker: bool = True  # run the queue consumer + scheduler inside the API process
    # Render sets RENDER_EXTERNAL_URL for every web service. With keep_awake on, the scheduler requests it every 10
    # minutes: the request comes back in through Render's front door, so a free instance never sleeps (a sleeping
    # one can't be woken by requests proxied through the Vercel site). Uses ~720 of the 750 free hours a month.
    render_external_url: str | None = None
    keep_awake: bool = True
    worker_poll_seconds: float = 2.0
    run_lock_timeout_minutes: int = 30

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Render / Railway / Heroku hand out postgres:// URLs; SQLAlchemy needs the driver spelled out.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @field_validator("cors_origins", "admin_emails", "github_listings_urls", "whatsapp_template_langs", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _refuse_unsafe_prod(self):
        """Fail at boot, not after a breach: production needs real secrets and secure cookies."""
        if self.env != "prod":
            return self
        problems = []
        if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a random value of at least 32 characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (the site is served over HTTPS)")
        if not self.encryption_key:
            problems.append("ENCRYPTION_KEY must be set (encrypts users' mail passwords)")
        if any("localhost" in o for o in self.cors_origins) or not self.cors_origins:
            problems.append("CORS_ORIGINS must list your real web origin(s)")
        if problems:
            raise ValueError("Unsafe production config: " + "; ".join(problems))
        return self

    def limits(self, plan: str) -> dict[str, float]:
        return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq URL for psycopg (LangGraph checkpointer)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def models(self) -> tuple[str, str]:
        fast, smart = PROVIDER_MODELS[self.llm_provider]
        return self.fast_model or fast, self.smart_model or smart

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode == "offline":
            return False
        if self.llm_mode == "on":
            return True
        return bool(self.groq_api_key if self.llm_provider == "groq" else self.anthropic_api_key)

    @property
    def llm_label(self) -> str:
        return self.llm_provider if self.llm_enabled else "offline"

    @property
    def smtp_enabled(self) -> bool:
        # A login user without a password can't authenticate, so don't offer sending.
        return bool(self.smtp_host and self.smtp_from and (not self.smtp_user or self.smtp_password))

    @property
    def payments_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret and self.razorpay_webhook_secret)

    @property
    def google_mail_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id and self.whatsapp_template)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

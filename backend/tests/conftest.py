import os

os.environ.update(
    ENV="test",
    DATABASE_URL=os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/jobpilot_test"),
    LLM_MODE="offline",
    LLM_PROVIDER="groq",
    FAST_MODEL="",
    SMART_MODEL="",
    EMBEDDING_BACKEND="hash",
    EMBEDDED_WORKER="false",
    DEMO_SOURCE="true",
    PUBLIC_FEEDS_ENABLED="false",
    SEED_COMPANY_BOARDS="false",
    RESEARCHER_ENABLED="false",
    HUNTER_API_KEY="",
    JSEARCH_API_KEY="",
    VERIFY_LINKS="false",
    WEBSITE_CONTACTS_ENABLED="false",
    SMTP_HOST="",
    SMTP_USER="",
    SMTP_PASSWORD="",
    SMTP_FROM="",
    SOURCE_CACHE_S="0",
    ADZUNA_APP_ID="",
    ADZUNA_APP_KEY="",
    FANOUT_MIN_SEMANTIC="0",
    RATE_LIMITS_ENABLED="false",
    ADMIN_EMAILS="",
    SCAM_FETCH_URLS="false",
    SCAM_RDAP_ENABLED="false",
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

TABLES = "audit_events, transparency_daily, alumni, gap_projects, interview_sessions, stipend_reports, payment_events, payments, whatsapp_events, proof_link_views, proof_links, approval_events, quotas, scam_reports, verifications, rights_requests, drive_statuses, campus_drives, org_members, organizations, api_tokens, consents, mail_accounts, password_resets, rate_limits, board_probes, source_targets, company_contacts, notifications, skill_questions, reminders, outreach_drafts, tailored_resumes, llm_calls, job_matches, agent_runs, jobs, profiles, users"


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean_db():
    import app.services.ingest as ingest

    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    ingest._last_sync = None
    yield


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def authed(client):
    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "aarav@example.com", "password": "password123", "name": "Aarav"})
    assert r.status_code == 201
    client.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    return client

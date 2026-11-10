"""v2 features from the research paper: consent, proof-of-skills, referrals + quality gate, ghost-job risk,
outcomes, campus mode, WhatsApp digest and the Chrome extension API."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import respx
from sqlalchemy import select, text

from app.config import settings
from app.db import session_scope
from app.models import CampusDrive, Consent, JobMatch, Profile
from app.services.campus import eligibility
from app.services.job_store import ghost_assessment
from app.services.runs import claim_next, execute_run
from app.sources.base import Posting

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def _upload(c):
    assert (await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})).status_code == 200


async def _work():
    claimed = await claim_next("w")
    return await execute_run(claimed.id, claimed.user_id)


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------- consent ----------


async def test_registration_needs_consent_and_records_it(client):
    r = await client.post("/api/auth/register", json={"email": "x@example.com", "password": "password123"})
    assert r.status_code == 422 and "privacy" in r.json()["detail"]
    r = await client.post("/api/auth/register", json={"consent": True, "email": "x@example.com", "password": "password123"})
    assert r.status_code == 201
    c = (await client.get("/api/consents")).json()
    core = next(p for p in c["purposes"] if p["purpose"] == "core")
    assert core["granted"] and core["required"]
    assert (await client.put("/api/consents/core", json={"granted": False})).status_code == 409


# ---------- proof of skills ----------

GH_USER = {"login": "aarav", "html_url": "https://github.com/aarav", "bio": "ML student · jobpilot-abc123", "followers": 4, "created_at": "2023-01-02T00:00:00Z"}
GH_REPOS = [
    {"name": "rag-search", "html_url": "https://github.com/aarav/rag-search", "description": "RAG search with FastAPI", "language": "Python", "stargazers_count": 12,
     "topics": ["llm", "fastapi"], "pushed_at": datetime.now(UTC).isoformat(), "fork": False},
    {"name": "fork-of-x", "html_url": "https://github.com/aarav/x", "language": "Go", "stargazers_count": 99, "fork": True},
]


@respx.mock
async def test_github_evidence_verified_by_bio_code_and_public_only_with_consent(authed):
    respx.get("https://api.github.com/users/aarav").mock(return_value=httpx.Response(200, json=GH_USER))
    respx.get("https://api.github.com/users/aarav/repos").mock(return_value=httpx.Response(200, json=GH_REPOS))
    ev = (await authed.put("/api/evidence/github", json={"handle": "https://github.com/aarav"})).json()
    gh = ev["github"]
    assert gh["public_repos"] == 1 and gh["stars"] == 12 and not gh["verified"]  # forks don't count
    assert "FastAPI" in ev["skills"] or "Python" in ev["skills"]

    async with session_scope() as s:
        p = (await s.execute(select(Profile))).scalar_one()
        p.evidence = {**p.evidence, "verify_code": "jobpilot-abc123"}
    assert (await authed.post("/api/evidence/github/verify")).json()["github"]["verified"]

    assert not ev["public"]
    pub = (await authed.put("/api/evidence/public", json={"public": True})).json()
    slug = pub["slug"]
    page = (await authed.get(f"/api/public/proof/{slug}")).json()
    assert page["github"]["verified"] and "email" not in json.dumps(page).lower().replace("email_body", "")
    await authed.put("/api/consents/public_proof", json={"granted": False})
    assert (await authed.get(f"/api/public/proof/{slug}")).status_code == 404  # withdrawn: unpublished at once


@respx.mock
async def test_codeforces_rating_is_linked(authed):
    respx.get("https://codeforces.com/api/user.info").mock(
        return_value=httpx.Response(200, json={"status": "OK", "result": [{"handle": "aarav", "rating": 1544, "maxRating": 1610, "rank": "specialist"}]})
    )
    cf = (await authed.put("/api/evidence/codeforces", json={"handle": "aarav"})).json()["codeforces"]
    assert cf["rating"] == 1544 and cf["rank"] == "specialist"


# ---------- referrals, quality gate, ghost jobs ----------


async def test_every_application_comes_with_a_guarded_referral_request(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    drafts = (await authed.get("/api/drafts")).json()
    apps = [d for d in drafts if d["kind"] == "application"]
    refs = [d for d in drafts if d["kind"] == "referral"]
    assert apps and len(refs) == len(apps)
    assert all("refer" in d["email_body"].lower() for d in refs)


async def test_weekly_cap_limits_tailoring(authed):
    await _upload(authed)
    prefs = (await authed.get("/api/profile")).json()["preferences"]
    await authed.put("/api/profile", json={"preferences": {**prefs, "weekly_application_cap": 3}})
    await authed.post("/api/runs")
    await _work()
    usage = (await authed.get("/api/usage")).json()
    assert usage["week_applications"] <= 3 and usage["weekly_cap"] == 3


def test_ghost_risk_signals():
    now = datetime.now(UTC)
    fresh = Posting(source="greenhouse", external_id="1", company="A", title="ML Intern", description="Requirements: Python. " * 40, posted_at=now - timedelta(days=3))
    assert ghost_assessment(fresh, "ok", 0, now)[0] == "low"
    stale = Posting(source="adzuna", external_id="2", company="B", title="Intern", description="Great opportunity", posted_at=now - timedelta(days=60))
    risk, reasons = ghost_assessment(stale, "unverified", 3, now)
    assert risk == "high" and any("Reposted" in r for r in reasons)


async def test_high_ghost_risk_jobs_are_never_tailored(authed, monkeypatch):
    monkeypatch.setattr("app.services.job_store.ghost_assessment", lambda p, link, reposts, now: ("high", ["Reposted 4 times in 90 days"]))
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    async with session_scope() as s:
        tailored = (await s.execute(text("SELECT count(*) FROM tailored_resumes"))).scalar()
        risky = (await s.execute(text("SELECT count(*) FROM jobs WHERE ghost_risk = 'high'"))).scalar()
    assert risky > 0 and tailored == 0
    item = (await authed.get("/api/matches")).json()["items"][0]["job"]
    assert item["ghost_risk"] == "high" and item["ghost_reasons"]


# ---------- outcomes ----------


async def test_outcomes_feed_insights_and_rejection_gaps(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    items = (await authed.get("/api/matches", params={"limit": 6})).json()["items"]
    outcomes = ["interview", "rejected", "rejected", "replied", "no_reply", "offer"]
    for m, o in zip(items, outcomes):
        r = await authed.patch(f"/api/matches/{m['id']}", json={"outcome": o, "rejection_reason": "Skills didn't match" if o == "rejected" else None})
        assert r.json()["outcome"] == o
    assert (await authed.get(f"/api/matches/{items[0]['id']}")).json()["stage"] == "interview"  # moves the Kanban card
    ins = (await authed.get("/api/insights")).json()
    n = min(len(items), 6)
    assert ins["applied"] == n and ins["funnel"]["interview"] == 2 and ins["interview_rate"] == round(200 / n, 1)
    assert {v["key"][0] for v in ins["by_variant"]} <= {"A", "B"} and ins["reasons"][0]["reason"] == "Skills didn't match"
    assert ins["reason_options"]


# ---------- campus ----------


def test_drive_eligibility():
    d = CampusDrive(company="Acme", role="SDE Intern", eligibility={"min_cgpa": 7.5, "branches": ["CSE", "IT"], "max_backlogs": 0, "grad_years": [2027]})
    assert eligibility(d, {"cgpa": 8.1, "branch": "CSE", "backlogs": 0, "grad_year": 2027}) == (True, [])
    ok, why = eligibility(d, {"cgpa": 7.0, "branch": "Mechanical", "backlogs": 1, "grad_year": 2027})
    assert ok is False and len(why) == 3
    assert eligibility(d, {})[0] is None  # can't tell yet


async def test_college_dashboard_shows_only_students_who_share(authed, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", ["aarav@example.com"])
    org = (await authed.post("/api/admin/orgs", json={"name": "Mumbai Institute of Technology"})).json()
    officer = await _client()
    r = await officer.post("/api/auth/register", json={"consent": True, "email": "tpo@mit.example", "password": "password123", "name": "TPO"})
    officer.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    await authed.post(f"/api/admin/orgs/{org['id']}/officers", json={"email": "tpo@mit.example"})

    s1, s2 = await _client(), await _client()
    for c, email, share in ((s1, "s1@mit.example", True), (s2, "s2@mit.example", False)):
        r = await c.post("/api/auth/register", json={"consent": True, "email": email, "password": "password123"})
        c.headers["authorization"] = f"Bearer {r.json()['access_token']}"
        assert (await c.post("/api/campus/join", json={"invite_code": org["invite_code"].lower(), "share_progress": share})).status_code == 200
        await c.put("/api/campus/academics", json={"college": "MIT", "branch": "CSE", "grad_year": 2027, "cgpa": 8.0, "backlogs": 0})

    drive = (await officer.post("/api/college/drives", json={"company": "Acme", "role": "SDE Intern", "eligibility": {"min_cgpa": 7.5, "branches": ["CSE"]},
                                                          "register_by": (datetime.now(UTC) + timedelta(days=3)).isoformat(), "rounds": [{"name": "Online test", "type": "coding"}]})).json()
    mine = (await s1.get("/api/campus")).json()
    assert mine["college"]["name"].startswith("Mumbai") and mine["drives"][0]["eligible"] and mine["summary"]["eligible_upcoming"] == 1
    assert mine["drives"][0]["prep"][0]["checklist"]
    await s1.put(f"/api/campus/drives/{drive['id']}/status", json={"status": "registered"})

    dash = (await officer.get("/api/college")).json()
    assert dash["students"] == 2 and dash["sharing"] == 1
    assert [p["email"] for p in dash["per_student"]] == ["s1@mit.example"]  # the non-sharing student is aggregate-only
    assert dash["drives"][0]["eligible_students"] == 2 and dash["drives"][0]["statuses"] == {"registered": 1}
    assert (await s1.get("/api/college")).status_code == 403
    for c in (officer, s1, s2):
        await c.aclose()


# ---------- WhatsApp ----------


@respx.mock
async def test_whatsapp_digest_needs_keys_and_consent_and_stop_opts_out(authed, monkeypatch):
    from app.services.whatsapp import IST, digest_sweep

    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    assert (await authed.put("/api/whatsapp", json={"number": "98765 43210", "hour": 9, "consent": False})).status_code == 422
    out = (await authed.put("/api/whatsapp", json={"number": "98765 43210", "hour": 9, "consent": True})).json()
    assert out["number"] == "919876543210" and out["enabled"] and not out["available"]

    now = datetime(2026, 11, 4, 9, 5, tzinfo=IST).astimezone(UTC)
    assert await digest_sweep(now) == 0  # no keys: nothing is sent
    for k, v in {"whatsapp_token": "t", "whatsapp_phone_number_id": "123", "whatsapp_app_secret": "s3cret"}.items():
        monkeypatch.setattr(settings, k, v)
    async with session_scope() as s:  # make today's matches count as new and strong
        await s.execute(text("UPDATE job_matches SET created_at = :t, score = 90"), {"t": now - timedelta(hours=1)})
    route = respx.post("https://graph.facebook.com/v21.0/123/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid"}]}))
    assert await digest_sweep(now) == 1 and await digest_sweep(now) == 0  # once a day
    sent = json.loads(route.calls[0].request.content)
    assert sent["to"] == "919876543210" and sent["template"]["name"] == settings.whatsapp_template
    assert "\n" not in sent["template"]["components"][0]["parameters"][1]["text"]

    payload = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"from": "919876543210", "text": {"body": "STOP"}}]}}]}]}).encode()
    bad = await authed.post("/api/whatsapp/webhook", content=payload, headers={"x-hub-signature-256": "sha256=nope", "content-type": "application/json"})
    assert bad.status_code == 401
    sig = "sha256=" + hmac.new(b"s3cret", payload, hashlib.sha256).hexdigest()
    ok = await authed.post("/api/whatsapp/webhook", content=payload, headers={"x-hub-signature-256": sig, "content-type": "application/json"})
    assert ok.json()["opted_out"] == 1
    assert not (await authed.get("/api/whatsapp")).json()["enabled"]


# ---------- Chrome extension ----------


async def test_extension_token_autofill_and_applied(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    t = (await authed.post("/api/extension/tokens", json={"name": "Laptop"})).json()["token"]
    assert t.startswith("jpx_") and len((await authed.get("/api/extension/tokens")).json()) == 1

    ext = await _client()
    ext.headers["authorization"] = f"Bearer {t}"
    async with session_scope() as s:
        m = (await s.execute(select(JobMatch).order_by(JobMatch.score.desc()).limit(1))).unique().scalar_one()
        job = m.job
    data = (await ext.get("/api/extension/autofill", params={"url": job.url or "https://example.com/none"})).json()
    assert data["applicant"]["email"] and data["applicant"]["first_name"]
    if data["matched"]:
        assert data["match_id"] == str(m.id)
        pdf = await ext.get(data["resume_path"].removeprefix(""))
        assert pdf.content.startswith(b"%PDF")
        done = (await ext.post("/api/extension/applied", json={"match_id": data["match_id"]})).json()
        assert done["stage"] == "applied" and done["resume_variant"] in ("A", "B")
    assert (await ext.get("/api/auth/me")).status_code == 401  # extension tokens only open /api/extension

    tok_id = (await authed.get("/api/extension/tokens")).json()[0]["id"]
    await authed.delete(f"/api/extension/tokens/{tok_id}")
    assert (await ext.get("/api/extension/autofill", params={"url": "https://x"})).status_code == 401
    await ext.aclose()


def test_extension_url_matching():
    from app.api.routes.extension import external_ids

    assert external_ids("https://boards.greenhouse.io/acme/jobs/4012345?gh_src=x") == [("greenhouse", "acme:4012345")]
    assert external_ids("https://job-boards.greenhouse.io/Stripe/jobs/77") == [("greenhouse", "stripe:77")]
    assert external_ids("https://jobs.lever.co/beta-co/1b2c-uuid/apply") == [("lever", "beta-co:1b2c-uuid")]
    assert external_ids("https://jobs.ashbyhq.com/sarvam/9f8e/application") == [("ashby", "sarvam:9f8e")]
    assert external_ids("https://linkedin.com/jobs/view/1") == []


async def test_consent_rows_are_kept_when_withdrawn(authed):
    await authed.put("/api/consents/whatsapp", json={"granted": True})
    await authed.put("/api/consents/whatsapp", json={"granted": False})
    async with session_scope() as s:
        rows = (await s.execute(select(Consent).where(Consent.purpose == "whatsapp"))).scalars().all()
    assert len(rows) == 1 and rows[0].withdrawn_at is not None

"""The Verifier's verdicts, and its place in a real run."""

import uuid

from sqlalchemy import select

from app.agents.verifier import assess
from app.db import session_scope
from app.models import Job
from tests.test_pipeline import _upload, _work


def _job(**kw) -> Job:
    base = dict(
        id=uuid.uuid4(), source="adzuna", external_id="x", company="Acme Analytics", title="Data Analyst Intern", location="Pune",
        description="Requirements: SQL and Python. You will build dashboards with the analytics team.", url="https://jobs.lever.co/acme/1",
        apply_links=[{"url": "https://jobs.lever.co/acme/1", "direct": True}], link_status="ok", recruiter_email=None, company_domain="acme.com",
        salary_min=None, salary_max=None, ghost_risk="low", ghost_reasons=[],
    )
    return Job(**{**base, **kw})


def test_clean_posting_on_a_careers_system_is_verified():
    v = assess(_job())
    assert v.status == "verified" and not v.reasons
    assert any("careers system" in g for g in v.good)


def test_red_flags_make_a_job_suspicious():
    assert assess(_job(description="Great role! Pay the training fee of 2000, refundable after 3 months.")).status == "suspicious"
    assert assess(_job(description="Contact us on WhatsApp to get selected. Requirements: none.")).status == "suspicious"
    assert assess(_job(company="Leading MNC")).status == "suspicious"


def test_phrases_only_match_whole_words():
    # A real posting: "Internship Feeling..." must not read as "internship fee".
    v = assess(_job(description="Paid Internship Feeling ready to spread your wings? Requirements: Python. You will analyse technical data."))
    assert v.status == "verified"


def test_softer_signals_ask_for_caution():
    v = assess(_job(recruiter_email="hr.acme.jobs@gmail.com", link_status="unverified", apply_links=[{"url": "https://acme-careers.example/1", "direct": False}], url="https://acme-careers.example/1"))
    assert v.status == "caution"
    assert any("personal email" in r for r in v.reasons) and any("couldn’t be opened" in r for r in v.reasons)
    assert assess(_job(description="Urgent hiring! Limited seats. Requirements: Excel.")).status == "caution"


async def test_run_includes_verifier_and_blocks_suspicious_jobs(authed, monkeypatch):
    from app.sources.base import Posting
    from app.sources.providers import DemoSource

    real_fetch = DemoSource.fetch

    async def with_scam(self, client, prefs):
        rows = await real_fetch(self, client, prefs)
        good = rows[0]
        # A well-matched posting that asks for a training fee: it passes ingest's filter, the Verifier catches it.
        scam = Posting(**{**good.__dict__, "external_id": "scam-1", "company": "Brightpath Labs", "description": good.description + "\n\nSelected candidates must buy our starter kit before joining."})
        return [*rows, scam]

    monkeypatch.setattr(DemoSource, "fetch", with_scam)
    await _upload(authed)
    r = await authed.post("/api/runs")
    await _work()
    run = (await authed.get(f"/api/runs/{r.json()['id']}")).json()
    steps = {st["agent"]: st for st in run["steps"]}
    assert steps["verifier"]["status"] == "completed" and "blocked as suspicious" in steps["verifier"]["detail"]
    assert run["stats"]["suspicious"] >= 1 and run["stats"]["verified"] >= 1

    async with session_scope() as s:
        scam = (await s.execute(select(Job).where(Job.external_id == "scam-1"))).scalar_one()
    assert scam.legit_status == "suspicious" and any("kit" in r for r in scam.legit_reasons)
    matched = {m["job"]["id"] for m in (await authed.get("/api/matches", params={"limit": 500})).json()["items"]}
    assert str(scam.id) not in matched  # never reaches the Matcher

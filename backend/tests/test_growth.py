"""Step 9: stipend & PPO ledger (k >= 3), JD-specific mock interviews, gap-to-proof with before/after in the trace."""

import re
from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import select, update

from app.api.routes.ledger import market_check
from app.db import session_scope
from app.models import AgentRun, Job, JobMatch, Profile, StipendReport, User

JD = (
    "We are hiring a Data Analyst Intern. Requirements: Experience writing SQL queries on large datasets. "
    "Knowledge of Python and pandas for analysis. Ability to build dashboards in Tableau. "
    "Strong communication skills to present findings to the team. Familiarity with Docker is a plus. " * 2
)


async def _ledger_user(c, email):
    r = await c.post("/api/auth/register", json={"consent": True, "adult": True, "email": email, "password": "password123"})
    c.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    assert (await c.put("/api/consents/ledger", json={"granted": True})).status_code == 200


async def _report_and_verify(c, monkeypatch, stipend=15000, company="Acme Analytics Pvt Ltd"):
    sent = {}

    async def fake_mail(to, subject, body):
        sent["code"] = re.search(r"\d{6}", body).group(0)
        return True

    monkeypatch.setattr("app.api.routes.ledger.send_system_email", fake_mail)
    r = (await c.post("/api/ledger/reports", json={"company": company, "role": "Data Intern", "stipend": stipend, "duration_months": 3, "mode": "hybrid", "ppo_offered": True, "paid_on_time": True})).json()
    assert (await c.post(f"/api/ledger/reports/{r['id']}/otp", json={"college_email": "me@pict.edu.in"})).status_code == 200
    return (await c.post(f"/api/ledger/reports/{r['id']}/otp/verify", json={"code": sent["code"]})).json()


async def test_ledger_needs_consent_and_hides_companies_below_three(client, monkeypatch):
    from app.main import app

    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "noconsent@example.com", "password": "password123"})
    client.headers["authorization"] = f"Bearer {r.json()['access_token']}"
    assert (await client.post("/api/ledger/reports", json={"company": "Acme", "stipend": 10000, "duration_months": 2, "mode": "remote", "ppo_offered": False, "paid_on_time": True})).status_code == 403

    out = []
    for i in range(3):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            await _ledger_user(c, f"s{i}@example.com")
            out.append(await _report_and_verify(c, monkeypatch, stipend=[12000, 15000, 18000][i], company=["Acme Analytics Pvt Ltd", "acme analytics", "Acme Analytics Private Limited"][i]))
            if i == 1:
                assert (await c.get("/api/ledger/companies")).json() == []  # two reports: nothing shown
            if i == 2:
                export = (await c.get("/api/account/export")).json()
                assert len(export["stipend_reports"]) == 1  # only this student's own report
    assert all(r["status"] == "published" and r["verified_via"] == "college_email" for r in out)
    [agg] = (await client.get("/api/ledger/companies")).json()
    assert agg["reports"] == 3 and agg["median_stipend"] == 15000 and agg["ppo_rate"] == 1.0
    async with session_scope() as s:
        assert "below" in await market_check(s, "Acme Analytics", 5000)
        assert await market_check(s, "Acme Analytics", 14000) is None


async def test_outliers_and_offer_letters_go_to_moderation(authed, monkeypatch):
    assert (await authed.put("/api/consents/ledger", json={"granted": True})).status_code == 200
    big = await _report_and_verify(authed, monkeypatch, stipend=250000)
    assert big["status"] == "flagged"
    r = (await authed.post("/api/ledger/reports", json={"company": "Beta", "stipend": 10000, "duration_months": 2, "mode": "onsite", "ppo_offered": False, "paid_on_time": False})).json()
    await authed.post(f"/api/ledger/reports/{r['id']}/offer-letter", files={"file": ("offer.pdf", b"%PDF-1.4 offer letter", "application/pdf")})
    async with session_scope() as s:
        row = await s.get(StipendReport, r["id"])
        assert row.doc_enc and b"offer letter" not in row.doc_enc and row.doc_hash
        await s.execute(update(User).values(is_admin=True))
    queue = (await authed.get("/api/ledger/admin/queue")).json()
    assert {q["id"] for q in queue} == {big["id"], r["id"]}
    assert (await authed.post(f"/api/ledger/admin/reports/{r['id']}", json={"approve": True})).json()["verified_via"] == "offer_letter"
    async with session_scope() as s:
        row = await s.get(StipendReport, r["id"])
        assert row.doc_enc is None and row.doc_hash  # letter deleted, hash kept
    assert (await authed.put("/api/consents/ledger", json={"granted": False})).status_code == 200
    async with session_scope() as s:
        assert {x.status for x in (await s.execute(select(StipendReport))).scalars()} == {"withdrawn"}


async def _match(skills=("Python",), gaps=None) -> str:
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(resume={"name": "Aarav", "skills": list(skills)}, evidence={"github": {"verified": True, "username": "aarav", "top_repos": [{"name": "churn-model", "language": "Python"}]}}))
        j = Job(source="t", external_id="g1", company="Acme", title="Data Analyst Intern", description=JD, skills=["SQL", "Python", "Tableau", "Docker"])
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=58.0, semantic_score=60, skill_score=25, strengths=["Python"], gaps=gaps or ["SQL", "Tableau", "Docker"])
        s.add(m)
        await s.flush()
        return str(m.id)


async def test_mock_interview_cites_the_jd_and_feeds_skills(authed):
    mid = await _match()
    sess = (await authed.post("/api/interviews", json={"match_id": mid})).json()
    qs = sess["questions"]
    assert 5 <= len(qs) <= 16 and all(q["jd_line"] for q in qs)  # sized to the interview length (45 min by default)
    sql_q = next(q for q in qs if q.get("skill") == "SQL")
    assert "SQL" in sql_q["jd_line"]
    weak = (await authed.post(f"/api/interviews/{sess['id']}/answer", json={"question_id": qs[-1]["id"], "answer": "I like it."})).json()
    assert weak["scores"][qs[-1]["id"]]["score"] < 3
    good = "In my college project I wrote SQL queries on a 2 million row sales dataset. I built joins and window functions to find churned customers, which reduced the report time from 3 hours to 10 minutes and the team used it every week."
    out = (await authed.post(f"/api/interviews/{sess['id']}/answer", json={"question_id": sql_q["id"], "answer": good})).json()
    sc = out["scores"][sql_q["id"]]
    assert sc["score"] >= 4 and sc["tests"] == sql_q["jd_line"]
    assert (await authed.post(f"/api/interviews/{sess['id']}/apply-skills", json={"question_ids": [sql_q["id"]]})).json()["added"] == ["SQL"]
    async with session_scope() as s:
        m = await s.get(JobMatch, mid)
        assert "SQL" in m.strengths and m.score > 58.0


@respx.mock
async def test_gap_to_proof_verifies_the_repo_and_records_before_after(authed):
    mid = await _match()
    projects = (await authed.get(f"/api/matches/{mid}/gap-projects")).json()
    assert [p["skill"] for p in projects] == ["SQL", "Tableau"] and projects[0]["spec"]["deadline_hours"] == 48
    pushed = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    respx.get("https://api.github.com/repos/aarav/sales-sql").mock(return_value=httpx.Response(200, json={"owner": {"login": "aarav"}, "fork": False, "pushed_at": pushed, "description": "Sales analysis with SQL", "topics": ["sql"]}))
    respx.get("https://api.github.com/repos/aarav/sales-sql/languages").mock(return_value=httpx.Response(200, json={"PLpgSQL": 1000}))
    respx.get("https://api.github.com/repos/aarav/sales-sql/readme").mock(return_value=httpx.Response(200, text="# Sales\nSQL window functions"))
    bad = await authed.post(f"/api/gap-projects/{projects[0]['id']}/submit", json={"repo_url": "https://github.com/someoneelse/sales-sql"})
    assert bad.status_code == 409
    g = (await authed.post(f"/api/gap-projects/{projects[0]['id']}/submit", json={"repo_url": "https://github.com/aarav/sales-sql"})).json()
    assert g["status"] == "verified" and g["after_score"] > g["before_score"] == 58.0
    async with session_scope() as s:
        run = await s.get(AgentRun, g["run_id"])
        assert run.stats["rescore"] == {"match_id": mid, "before": 58.0, "after": g["after_score"]}
        assert any("58.0 →" in st["detail"] for st in run.steps)

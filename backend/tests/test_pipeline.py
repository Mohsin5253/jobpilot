"""End to end through the API + LangGraph: scout -> matcher -> tailor -> outreach -> (interrupt)
-> approvals -> resume -> dispatch -> tracker. Offline LLM, hash embeddings, bundled demo postings."""

from pathlib import Path

import httpx
import respx
from sqlalchemy import select

from app.db import session_scope
from app.models import AgentRun
from app.services.runs import claim_next, execute_run

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


async def _upload(c):
    r = await c.post("/api/profile/resume", files={"file": ("resume.md", SAMPLE.read_bytes(), "text/markdown")})
    assert r.status_code == 200, r.text
    return r.json()


async def _work():
    claimed = await claim_next("test-worker")
    assert claimed is not None
    return await execute_run(claimed.id, claimed.user_id)


async def test_auth_flow(client):
    r = await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "a@b.co", "password": "password123"})
    assert r.status_code == 201
    assert (await client.post("/api/auth/register", json={"consent": True, "adult": True, "email": "A@b.co", "password": "password123"})).status_code == 409
    assert (await client.post("/api/auth/login", json={"email": "a@b.co", "password": "wrong-pass"})).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 200  # cookie session
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_run_requires_resume(authed):
    assert (await authed.post("/api/runs")).status_code == 409


async def test_full_pipeline_with_human_approval(authed):
    profile = await _upload(authed)
    assert "scikit-learn" in profile["resume"]["skills"]

    r = await authed.post("/api/runs")
    assert r.status_code == 202
    run_id = r.json()["id"]
    assert (await authed.post("/api/runs")).json()["id"] == run_id  # one active run per user

    assert await _work() == "awaiting_approval"
    run = (await authed.get(f"/api/runs/{run_id}")).json()
    steps = {s["agent"]: s["status"] for s in run["steps"]}
    assert steps["scout"] == steps["matcher"] == steps["tailor"] == steps["outreach"] == "completed"
    assert steps["approval"] == "waiting"

    matches = (await authed.get("/api/matches")).json()
    assert matches["total"] > 0
    top = matches["items"][0]
    assert top["explanation"].startswith("Strong:")

    detail = (await authed.get(f"/api/matches/{top['id']}")).json()
    assert detail["tailored"]["guard_report"]["passed"]
    assert detail["tailored"]["bullets"]

    drafts = (await authed.get("/api/drafts")).json()
    assert drafts and all(d["status"] == "pending" for d in drafts)
    assert await claim_next("idle") is None  # nothing to do while waiting on a human

    first, *rest = drafts
    r = await authed.post(f"/api/drafts/{first['id']}/decision", json={"decision": "approve", "subject": "Edited"})
    assert r.json()["status"] == "approved" and r.json()["subject"] == "Edited"
    assert (await authed.post(f"/api/drafts/{first['id']}/decision", json={"decision": "reject", "reason": "Wrong role for me"})).status_code == 409
    for d in rest:
        await authed.post(f"/api/drafts/{d['id']}/decision", json={"decision": "reject", "reason": "Wrong role for me"})

    assert await _work() == "completed"
    run = (await authed.get(f"/api/runs/{run_id}")).json()
    steps = {s["agent"]: s for s in run["steps"]}
    assert steps["approval"]["status"] == "completed"
    assert steps["dispatch"]["status"] == "completed" and steps["tracker"]["status"] == "completed"
    assert run["stats"]["active_ms"] > 0

    applied = (await authed.get("/api/matches", params={"stage": "applied"})).json()
    assert applied["total"] == 1 and applied["items"][0]["follow_up_at"]

    overview = (await authed.get("/api/stats/overview")).json()
    assert overview["stage_counts"]["applied"] == 1 and overview["llm_mode"] == "offline"

    # A second run sees no new jobs: every agent still does its job on your open matches (re-checked, re-ranked)
    # and is ticked, saying what it found; nothing is skipped, and nothing you already know about is re-announced.
    await authed.post("/api/runs")
    assert await _work() == "completed"
    latest = (await authed.get("/api/runs")).json()[0]
    steps = {s["agent"]: s for s in latest["steps"]}
    bad = {k: (v["status"], v["detail"]) for k, v in steps.items() if v["status"] != "completed"}
    assert not bad, bad
    assert steps["verifier"]["detail"].startswith("Re-checked your") and steps["matcher"]["detail"].startswith("Re-ranked your")
    assert steps["approval"]["detail"].startswith("Up to date")


@respx.mock
async def test_failing_source_does_not_fail_run(authed):
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(return_value=httpx.Response(500))
    await _upload(authed)
    prefs = (await authed.get("/api/profile")).json()["preferences"]
    prefs["greenhouse_boards"] = ["broken-board"]
    await authed.put("/api/profile", json={"preferences": prefs})
    await authed.post("/api/runs")
    assert await _work() == "awaiting_approval"
    async with session_scope() as s:
        run = (await s.execute(select(AgentRun))).scalar_one()
    scout = next(st for st in run.steps if st["agent"] == "scout")
    assert "greenhouse: failed" in scout["detail"]


async def test_follow_up_reminders(authed):
    from datetime import UTC, datetime, timedelta

    from app.agents.tracker import follow_up_sweep
    from app.models import JobMatch

    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    top = (await authed.get("/api/matches")).json()["items"][0]
    await authed.patch(f"/api/matches/{top['id']}", json={"stage": "applied"})
    async with session_scope() as s:
        m = await s.get(JobMatch, top["id"])
        m.follow_up_at = datetime.now(UTC) - timedelta(minutes=1)
    assert await follow_up_sweep() == 1
    assert await follow_up_sweep() == 0  # idempotent
    reminders = (await authed.get("/api/reminders")).json()
    assert len(reminders) == 1 and "follow-up" in reminders[0]["message"]
    await authed.post(f"/api/reminders/{reminders[0]['id']}/dismiss")
    assert (await authed.get("/api/reminders")).json() == []


async def test_interviewer_questions_answer_and_rescore(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    assert await _work() == "awaiting_approval"
    first = (await authed.get("/api/runs")).json()[0]
    assert {s["agent"]: s["status"] for s in first["steps"]}["interviewer"] == "completed"

    questions = (await authed.get("/api/questions")).json()
    assert questions, "near-miss jobs should produce skill questions"
    assert (await authed.get("/api/stats/overview")).json()["open_questions"] == len(questions)
    q = questions[0]
    assert q["unlocks"] >= 1 and q["jobs"] and q["skill"] in q["question"]

    # A bare "yes" is rejected: the Tailor needs the user's own words to work with.
    r = await authed.post("/api/questions/answers", json={"answers": [{"id": q["id"], "has_skill": True, "details": "yes"}]})
    assert r.status_code == 422

    details = f"I used {q['skill']} in my final-year project for a course assignment and wrote a short report on it."
    r = await authed.post("/api/questions/answers", json={"answers": [{"id": q["id"], "has_skill": True, "details": details}]})
    body = r.json()
    assert r.status_code == 200 and body["skills_added"] == [q["skill"]] and body["rechecking_jobs"] >= 1 and body["rematch_run_id"]

    profile = (await authed.get("/api/profile")).json()
    assert q["skill"] in profile["resume"]["skills"]
    assert profile["resume"]["additional"][0]["details"] == details

    # The rescore run skips the Scout and the Interviewer and re-scores only the unlocked jobs.
    assert await _work() in ("completed", "awaiting_approval")
    run = (await authed.get(f"/api/runs/{body['rematch_run_id']}")).json()
    steps = {s["agent"]: s for s in run["steps"]}
    assert run["trigger"] == "skills"
    assert steps["scout"]["status"] == "skipped" and steps["interviewer"]["status"] == "skipped"
    assert steps["matcher"]["detail"].startswith("Re-scored")
    assert all(x["id"] != q["id"] for x in (await authed.get("/api/questions")).json())


async def test_draft_recipient_and_apply(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    drafts = (await authed.get("/api/drafts")).json()
    assert {d["kind"] for d in drafts} == {"application", "referral"}  # every application comes with a referral request
    with_email = [d for d in drafts if d["recruiter_email"] and d["kind"] == "application"]
    assert all(d["to_email"] == d["recruiter_email"] for d in with_email)  # pre-filled from the posting
    assert all(d["contact"]["source"] == "posting" and d["contact"]["sources"] for d in with_email)  # recipient carries its source
    d = drafts[0]
    assert (await authed.patch(f"/api/drafts/{d['id']}", json={"to_email": "not-an-email"})).status_code == 422
    r = await authed.patch(f"/api/drafts/{d['id']}", json={"to_email": "hiring@company.example"})
    assert r.json()["to_email"] == "hiring@company.example"
    await authed.post(f"/api/drafts/{d['id']}/decision", json={"decision": "approve"})
    # Still editable after approval, so the address can be fixed before opening the mail app.
    assert (await authed.patch(f"/api/drafts/{d['id']}", json={"to_email": "jobs@company.example"})).status_code == 200

    m = (await authed.get("/api/matches")).json()["items"][-1]
    r = await authed.post(f"/api/matches/{m['id']}/apply")
    assert r.json()["stage"] == "applied" and r.json()["follow_up_at"]


async def test_prepare_application_for_any_job(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    for d in (await authed.get("/api/drafts")).json():
        await authed.post(f"/api/drafts/{d['id']}/decision", json={"decision": "reject", "reason": "Wrong role for me"})
    await _work()  # finish the first run

    low = (await authed.get("/api/matches", params={"stage": "found"})).json()["items"][-1]  # lowest-scored job
    r = await authed.post(f"/api/matches/{low['id']}/prepare")
    assert r.status_code == 202 and r.json()["trigger"] == "prepare"
    assert (await authed.post(f"/api/matches/{low['id']}/prepare")).status_code == 409  # one run at a time
    assert await _work() == "awaiting_approval"
    run = (await authed.get(f"/api/runs/{r.json()['id']}")).json()
    steps = {s["agent"]: s["status"] for s in run["steps"]}
    assert steps["scout"] == steps["matcher"] == steps["interviewer"] == "skipped"
    assert steps["tailor"] == steps["outreach"] == "completed"
    detail = (await authed.get(f"/api/matches/{low['id']}")).json()
    assert detail["stage"] == "shortlisted" and detail["tailored"] and detail["drafts"][0]["status"] == "pending"


async def test_declined_bullet_keeps_original_wording(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    top = (await authed.get("/api/matches")).json()["items"][0]
    bullet = (await authed.get(f"/api/matches/{top['id']}")).json()["tailored"]["bullets"][0]

    r = await authed.patch(f"/api/matches/{top['id']}/tailored/bullets/{bullet['source_id']}", json={"declined": True})
    assert r.status_code == 200
    assert next(b for b in r.json()["bullets"] if b["source_id"] == bullet["source_id"])["declined"] is True

    from app.services import resume_doc
    from app.db import session_scope
    from app.models import JobMatch, Profile
    from app.schemas import ResumeData
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with session_scope() as s:
        m = (await s.execute(select(JobMatch).where(JobMatch.id == top["id"]).options(selectinload(JobMatch.tailored)))).scalar_one()
        profile = (await s.execute(select(Profile).where(Profile.user_id == m.user_id))).scalar_one()
        doc = resume_doc.build(ResumeData.model_validate(profile.resume), m)
    lines = [b for sec in doc.experience + doc.projects for b in sec.bullets]
    if bullet["rewritten"] != bullet["original"]:
        assert bullet["rewritten"] not in lines
    assert bullet["original"] in lines

    back = await authed.patch(f"/api/matches/{top['id']}/tailored/bullets/{bullet['source_id']}", json={"declined": False})
    assert next(b for b in back.json()["bullets"] if b["source_id"] == bullet["source_id"])["declined"] is False
    assert (await authed.patch(f"/api/matches/{top['id']}/tailored/bullets/nope", json={"declined": True})).status_code == 404


async def test_match_list_flags_approved_and_sent_drafts(authed):
    await _upload(authed)
    await authed.post("/api/runs")
    await _work()
    first = (await authed.get("/api/drafts")).json()[0]
    await authed.post(f"/api/drafts/{first['id']}/decision", json={"decision": "approve"})
    row = next(m for m in (await authed.get("/api/matches", params={"stage": "applied"})).json()["items"] if m["id"] == first["match_id"])
    assert row["approved_draft"] and not row["sent_draft"]
    await authed.post(f"/api/drafts/{first['id']}/mark-sent")
    row = next(m for m in (await authed.get("/api/matches", params={"stage": "applied"})).json()["items"] if m["id"] == first["match_id"])
    assert row["sent_draft"]
    assert (await authed.get(f"/api/matches/{first['match_id']}")).json()["sent_draft"]

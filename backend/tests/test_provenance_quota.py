"""Step 4: claim provenance (guard v2) and the quality quota."""

import random
from pathlib import Path

from sqlalchemy import select

from app.agents import tailor as tailor_mod
from app.agents.guard import GENERIC, bullet_contexts, check_claim, proof_contexts, resume_skillset
from app.agents.tailor import Rewrite, TailorOutput, tailor_one
from app.db import session_scope
from app.llm import CallContext
from app.models import ApprovalEvent, Job, JobMatch, OutreachDraft, Profile, User
from app.resume_parser import extract_text, heuristic_parse
from app.services import quota
from app.skills import SKILLS

SAMPLE = Path(__file__).resolve().parents[1] / "evals" / "data" / "sample_resume.md"


def _resume():
    text = extract_text("resume.md", SAMPLE.read_bytes())
    return heuristic_parse(text), text


def test_property_injected_claims_are_always_reverted():
    """Random fake skills and figures injected into real bullets: 100% must be caught."""
    resume, text = _resume()
    contexts = bullet_contexts(resume)
    have = resume_skillset(resume, text)
    fake_skills = [s for s in SKILLS if s not in have and s not in GENERIC]
    assert len(contexts) >= 4 and len(fake_skills) >= 50
    rng = random.Random(2026)
    cases = caught = 0
    for _ in range(400):
        sid, ctx = rng.choice(list(contexts.items()))
        line = ctx.split("\n", 1)[-1]
        kind = rng.choice(["skill", "number", "both"])
        injected = line.rstrip(".")
        if kind in ("skill", "both"):
            injected += f" using {rng.choice(fake_skills)}"
        if kind in ("number", "both"):
            injected += f", improving results by {rng.randint(13, 97)}{rng.choice(['%', 'x', ' users'])}"
        cases += 1
        caught += not check_claim(injected, [sid], contexts, have).ok
    assert caught == cases
    # The untouched line and a pure rephrase pass; no source at all never does.
    sid, ctx = next(iter(contexts.items()))
    assert check_claim(ctx.split("\n", 1)[-1], [sid], contexts, have).ok
    assert not check_claim(ctx.split("\n", 1)[-1], [], contexts, have).ok
    assert not check_claim(ctx.split("\n", 1)[-1], ["exp99.b9"], contexts, have).ok


def test_proof_items_are_sources_only_when_verified():
    resume, text = _resume()
    have = resume_skillset(resume, text)
    evidence = {"github": {"verified": False, "top_repos": [{"name": "rustdb", "language": "Rust", "description": "toy database", "topics": []}]}}
    assert proof_contexts(evidence) == {}
    evidence["github"]["verified"] = True
    proofs = proof_contexts(evidence)
    ctx = {**bullet_contexts(resume), **proofs}
    assert check_claim("Built a toy database in Rust", ["proof.gh.rustdb"], ctx, have | {"Rust"}).ok


class _FakeLLM:
    def __init__(self, out):
        self.out = out

    async def structured(self, **_):
        return self.out

    def model_for(self, _):
        return "fake"


async def test_tailor_records_sources_and_reverts_unsupported_bullets(monkeypatch):
    resume, text = _resume()
    index = dict(resume.bullet_index())
    (sid1, b1), (sid2, b2) = list(index.items())[:2]
    out = TailorOutput(
        bullets=[
            Rewrite(source_id=sid1, source_refs=[sid1], rewritten=b1, keywords=[]),
            Rewrite(source_id=sid2, source_refs=[sid2], rewritten=b2.rstrip(".") + " with Kubernetes, cutting costs by 41%", keywords=[]),
            Rewrite(source_id="exp42.b0", rewritten="Led a team of 12 engineers", keywords=[]),
        ]
    )
    monkeypatch.setattr(tailor_mod, "get_llm", lambda: _FakeLLM(out))
    job = Job(source="t", external_id="1", company="Acme", title="Intern", description="Python")
    match = JobMatch(job=job, strengths=[])
    bullets, report, _ = await tailor_one(match, resume, text, CallContext())
    by = {b["source_id"]: b for b in bullets}
    assert not by[sid1]["reverted"] and by[sid1]["source_refs"][0]["id"] == sid1 and by[sid1]["source_refs"][0]["label"].startswith(("Resume", "Skill"))
    assert by[sid2]["reverted"] and by[sid2]["rewritten"] == b2 and "41" in by[sid2]["revert_reason"]
    assert "exp42.b0" not in by and len(report["violations"]) == 2 and not report["passed"]


async def _drafts(n: int) -> tuple[User, list]:
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        ids = []
        for i in range(n):
            j = Job(source="t", external_id=str(i), company=f"Co{i}", title="Intern", description="Python " * 80, legit_status="verified", ghost_score=10)
            s.add(j)
            await s.flush()
            m = JobMatch(user_id=me.id, job_id=j.id, score=80)
            s.add(m)
            await s.flush()
            d = OutreachDraft(user_id=me.id, match_id=m.id, to_email=f"hr@co{i}.example", subject="Hi", email_body="Hello")
            s.add(d)
            await s.flush()
            ids.append(d.id)
        return me, ids


async def test_daily_quota_is_enforced_server_side(authed):
    me, ids = await _drafts(7)
    q = (await authed.get("/api/quota")).json()
    assert q == {**q, "cap": 5, "used": 0, "remaining": 5, "max": 10}
    listed = (await authed.get("/api/drafts")).json()
    assert all(0 < d["send_worthiness"] <= 100 and set(d["worthiness_parts"]) == {"fit", "verification", "not_ghost", "completeness"} for d in listed)
    for d in ids[:5]:
        assert (await authed.post(f"/api/drafts/{d}/decision", json={"decision": "approve"})).status_code == 200
    r = await authed.post(f"/api/drafts/{ids[5]}/decision", json={"decision": "approve"})
    assert r.status_code == 429 and "5" in r.json()["detail"]
    assert (await authed.get("/api/quota")).json()["remaining"] == 0
    # Rejecting never uses the quota.
    assert (await authed.post(f"/api/drafts/{ids[6]}/decision", json={"decision": "reject", "reason": "Wrong role for me"})).status_code == 200
    assert (await authed.put("/api/quota", json={"cap": 11})).status_code == 422
    assert (await authed.put("/api/quota", json={"cap": 6})).json()["remaining"] == 1
    assert (await authed.post(f"/api/drafts/{ids[5]}/decision", json={"decision": "approve"})).status_code == 200
    async with session_scope() as s:
        events = (await s.execute(select(ApprovalEvent))).scalars().all()
        assert sorted(e.action for e in events).count("approve") == 6 and all(e.channel == "web" and len(e.ip_hash) == 64 for e in events)
        approved = (await s.execute(select(OutreachDraft).where(OutreachDraft.status == "approved"))).scalars().all()
        assert all(d.send_worthiness and d.approval_channel == "web" for d in approved)


async def test_weekly_report_counts_what_was_skipped(authed, monkeypatch):
    sent = []

    async def fake_mail(to, subject, body):
        sent.append(body)
        return True

    monkeypatch.setattr("app.services.mailer.send_system_email", fake_mail)
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        for i, score in enumerate([30, 40, 85]):
            j = Job(source="t", external_id=f"w{i}", company="Co", title="Intern", ghost_risk="high" if i == 0 else "low")
            s.add(j)
            await s.flush()
            s.add(JobMatch(user_id=me.id, job_id=j.id, score=score))
        assert (await s.execute(select(Profile).where(Profile.user_id == me.id))).scalar_one()
    assert await quota.weekly_report() == 1
    assert "skipped 2 weak or risky matches" in sent[0] and "kept 1 strong" in sent[0]

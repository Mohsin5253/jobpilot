"""Step 10: drive-circular parser (>= 90% field accuracy), consent enforced by Postgres row-level security,
eligibility notifications, alumni referrals, audit log and the transparency report."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text, update

from app.db import session_scope
from app.models import AgentRun, AuditEvent, Consent, Job, JobMatch, Notification, Organization, OrgMember, Profile, User, Verification
from app.services.campus_v2 import officer_scope, parse_circular, transparency_sweep

DATA = Path(__file__).resolve().parents[1] / "evals" / "data"
FIELDS = ["company", "role", "compensation", "min_cgpa", "branches", "max_backlogs", "grad_years", "register_by", "rounds"]


def _accuracy(name: str) -> tuple[int, int]:
    ok = tot = 0
    for line in (DATA / name).read_text().splitlines():
        row = json.loads(line)
        p, e = parse_circular(row["text"], today=date(2026, 11, 10)), row["expected"]
        got = {
            "company": p["company"], "role": p["role"], "compensation": p["compensation"], "min_cgpa": p["eligibility"].get("min_cgpa"),
            "branches": sorted(p["eligibility"].get("branches", [])), "max_backlogs": p["eligibility"].get("max_backlogs"),
            "grad_years": p["eligibility"].get("grad_years", []), "register_by": p["register_by"], "rounds": [r["name"] for r in p["rounds"]],
        }
        for f in FIELDS:
            tot += 1
            g, x = got[f], e[f]
            ok += (x.lower() in (g or "").lower()) if f == "compensation" else ((g or "").strip().lower() == x.lower()) if f in ("company", "role") else g == x
    return ok, tot


def test_circular_parser_field_accuracy():
    ok, tot = _accuracy("drive_circulars.jsonl")
    assert tot >= 20 * len(FIELDS) and ok / tot >= 0.9, (ok, tot)
    ok, tot = _accuracy("drive_circulars_holdout.jsonl")  # written after tuning
    assert ok / tot >= 0.9, (ok, tot)


async def _college():
    async with session_scope() as s:
        org = Organization(name="PICT", slug="pict", invite_code="PICT26")
        s.add(org)
        await s.flush()
        users = {}
        for name, role in (("officer", "officer"), ("sharer", "student"), ("private", "student")):
            u = User(email=f"{name}@pict.example", name=name.title(), password_hash="x", adult_confirmed_at=datetime.now(UTC))
            s.add(u)
            await s.flush()
            s.add(Profile(user_id=u.id, resume={}, preferences={}, academics={"cgpa": 8.1, "branch": "CSE", "backlogs": 0, "grad_year": 2027}))
            s.add(OrgMember(org_id=org.id, user_id=u.id, role=role))
            users[name] = u
        s.add(Consent(user_id=users["sharer"].id, purpose="college_share", notice_version="2026-11"))
        for i, who in enumerate(("sharer", "private")):
            j = Job(source="t", external_id=f"c{i}", company="Acme", title="Intern")
            s.add(j)
            await s.flush()
            s.add(JobMatch(user_id=users[who].id, job_id=j.id, score=70, applied_at=datetime.now(UTC), outcome="interview"))
        return org, users


async def test_row_level_security_hides_students_who_dont_share(client):
    org, users = await _college()
    async with officer_scope(org.id) as s:
        seen = set((await s.execute(text("SELECT user_id FROM job_matches"))).scalars())  # even raw SQL
        profiles = set((await s.execute(select(Profile.user_id))).scalars())
    assert seen == {users["sharer"].id} and users["private"].id not in profiles
    async with session_scope() as s:  # outside an officer context nothing changes
        assert (await s.execute(select(func.count()).select_from(JobMatch))).scalar_one() == 2
        await s.execute(update(Consent).values(withdrawn_at=datetime.now(UTC)))  # the sharer withdraws
    async with officer_scope(org.id) as s:
        assert (await s.execute(text("SELECT count(*) FROM job_matches"))).scalar_one() == 0  # gone at once, not in 24h
    async with officer_scope(__import__("uuid").uuid4()) as s:  # another college sees nothing
        assert (await s.execute(text("SELECT count(*) FROM profiles"))).scalar_one() == 0


async def test_dashboard_aggregates_everyone_but_lists_only_sharers_and_is_audited(client):
    org, users = await _college()
    from app.security import create_token

    client.headers["authorization"] = f"Bearer {create_token(users['officer'].id, 0)}"
    d = (await client.get("/api/college")).json()
    assert d["students"] == 2 and d["sharing"] == 1
    assert [p["name"] for p in d["per_student"]] == ["Sharer"]
    async with session_scope() as s:
        ev = (await s.execute(select(AuditEvent))).scalar_one()
        assert ev.action == "tpo_view" and ev.detail == {"rows": 1}

    parsed = (await client.post("/api/college/drives/parse", json={"text": (DATA / "drive_circulars.jsonl").read_text().splitlines()[1] and json.loads((DATA / "drive_circulars.jsonl").read_text().splitlines()[1])["text"]})).json()
    assert parsed["company"] == "Persistent Systems" and parsed["eligibility"]["min_cgpa"] == 7.0
    body = {"company": parsed["company"], "role": parsed["role"], "compensation": parsed["compensation"], "eligibility": {"min_cgpa": 7.0, "branches": ["CSE"], "max_backlogs": 1, "grad_years": [2027]}, "rounds": []}
    r = (await client.post("/api/college/drives", json=body)).json()
    assert r["notified"] == 1  # the eligible student who shares; the other isn't notified
    async with session_scope() as s:
        n = (await s.execute(select(Notification).where(Notification.kind == "campus_drive"))).scalar_one()
        assert n.user_id == users["sharer"].id

    csv = "name,company,role,batch,contact,consent\nRavi K,Acme Analytics,Data Engineer,2023,https://example.com/ravi,yes\nNo Consent,Acme Analytics,SDE,2022,x,no\n"
    assert (await client.post("/api/college/alumni", json={"csv": csv})).json() == {"added": 1, "skipped_without_consent": 1}
    client.headers["authorization"] = f"Bearer {create_token(users['private'].id, 0)}"
    alumni = (await client.get("/api/campus/alumni", params={"company": "Acme Analytics Pvt Ltd"})).json()
    assert [a["name"] for a in alumni] == ["Ravi K"]


async def test_transparency_report(client):
    yesterday = datetime.now(UTC) - timedelta(days=1)
    async with session_scope() as s:
        u = User(email="t@example.com", password_hash="x")
        s.add(u)
        await s.flush()
        s.add_all([
            Verification(source="pipeline", input_hash="a", verdict="Likely scam", score=90, created_at=yesterday),
            Verification(source="pipeline", input_hash="b", verdict="Likely safe", score=0, created_at=yesterday),
            Verification(source="public", input_hash="c", verdict="Suspicious", score=30, created_at=yesterday),
            AgentRun(user_id=u.id, status="completed", cost_usd=0.002, created_at=yesterday),
        ])
    assert await transparency_sweep() == 35
    data = (await client.get("/api/public/transparency")).json()
    day = next(d for d in data["days"] if d["date"] == yesterday.date().isoformat())
    assert day["postings_verified"] == 2 and day["scams_flagged"] == 1 and day["scam_checks"] == 1 and day["avg_cost_inr"] > 0
    assert data["months"] and all("avg_cost_inr" in m for m in data["months"])

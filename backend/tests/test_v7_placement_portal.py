"""The placement-cell portal: staff codes (hashed, shown once), TPO / HOD / teacher roles with department scope,
consent-gated student data, AI match proposals staff approve, rounds to placed, precision@5, college-only jobs,
campus pricing enquiries, and skill-family matching."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, CampusPlacement, Consent, Job, JobMatch, Notification, Organization, OrgMember, Profile, User
from app.security import create_token
from app.services import placement as pc
from app.skills import adjacent, skill_overlap

RESUME = {"name": "S", "skills": ["Python", "SQL", "FastAPI", "PostgreSQL", "Docker"], "projects": [{"name": "Campus Eats", "tech": ["FastAPI"], "bullets": ["Built a FastAPI service with PostgreSQL for 200 students."]}]}


async def _college():
    from app.agents.matcher import ensure_profile_embedding
    from app.schemas import ResumeData

    async with session_scope() as s:
        org = Organization(name="COEP", slug="coep", invite_code="COEP26", domain="coep.ac.in")
        s.add(org)
        await s.flush()
        users = {}
        for name, role, branch, dept in (
            ("tpo", "tpo", "", ""),
            ("hodcs", "hod", "", "Computer Engineering"),
            ("teacher", "teacher", "", "Mechanical"),
            ("cs1", "student", "Computer Engineering", ""),
            ("mech1", "student", "Mechanical Engineering", ""),
            ("private", "student", "Computer Engineering", ""),
        ):
            u = User(email=f"{name}@coep.ac.in", name=name.upper(), password_hash="x", adult_confirmed_at=datetime.now(UTC))
            s.add(u)
            await s.flush()
            s.add(Profile(user_id=u.id, resume=RESUME if role == "student" else {}, preferences={}, academics={"branch": branch, "cgpa": 8.0, "grad_year": 2027} if branch else {}))
            s.add(OrgMember(org_id=org.id, user_id=u.id, role=role, department=dept))
            users[name] = u
        for who in ("cs1", "mech1"):
            s.add(Consent(user_id=users[who].id, purpose="college_share", notice_version="2026-11"))
    for who in ("cs1", "mech1", "private"):
        async with session_scope() as s:
            p = (await s.execute(select(Profile).where(Profile.user_id == users[who].id))).scalar_one()
        await ensure_profile_embedding(p.id, ResumeData.model_validate(RESUME))
    return org, users


def _as(client, user):
    client.headers["authorization"] = f"Bearer {create_token(user.id, 0)}"
    return client


async def test_staff_code_is_hashed_shown_once_and_gated(client):
    org, users = await _college()
    c = _as(client, users["tpo"])
    code = (await c.post("/api/college/staff-code")).json()["code"]
    async with session_scope() as s:
        o = await s.get(Organization, org.id)
        assert o.staff_code_hash and code not in o.staff_code_hash and o.staff_code_hash == pc.hash_code(code)
    assert (await c.get("/api/college/me")).json()["staff_code_set"] is True

    # A new staff member: wrong code, wrong domain, then right.
    async with session_scope() as s:
        outsider = User(email="newhod@gmail.com", name="X", password_hash="x", adult_confirmed_at=datetime.now(UTC))
        insider = User(email="newhod@coep.ac.in", name="New HOD", password_hash="x", adult_confirmed_at=datetime.now(UTC))
        s.add_all([outsider, insider])
    j = {"code": code, "role": "hod", "department": "Computer Engineering"}
    assert (await _as(client, outsider).post("/api/college/staff/join", json=j)).status_code == 403
    assert (await _as(client, insider).post("/api/college/staff/join", json={**j, "code": "STAFF-WRNG-CODE-0000"})).status_code == 404
    assert (await _as(client, insider).post("/api/college/staff/join", json={**j, "role": "tpo"})).status_code == 422  # TPO isn't self-selected
    r = await _as(client, insider).post("/api/college/staff/join", json={**j, "code": code.lower().replace("-", " - ")})
    assert r.status_code == 200 and r.json()["label"] == "Head of Department"
    # Only a TPO manages staff.
    assert (await _as(client, users["hodcs"]).post("/api/college/staff-code")).status_code == 403
    staff = (await _as(client, users["tpo"]).get("/api/college/staff")).json()
    assert {s["role"] for s in staff} == {"tpo", "hod", "teacher"}


async def test_department_scope_and_consent(client):
    org, users = await _college()
    tpo = (await _as(client, users["tpo"]).get("/api/college/students")).json()
    assert tpo["total_students"] == 3 and {s["name"] for s in tpo["students"]} == {"CS1", "MECH1"}  # PRIVATE never listed
    hod = (await _as(client, users["hodcs"]).get("/api/college/students")).json()
    assert [s["name"] for s in hod["students"]] == ["CS1"] and hod["scope"] == "Computer Engineering"
    teacher = (await _as(client, users["teacher"]).get("/api/college/students")).json()
    assert [s["name"] for s in teacher["students"]] == ["MECH1"]
    async with session_scope() as s:
        actions = [e.action for e in (await s.execute(select(AuditEvent))).scalars()]
    assert actions.count("staff_student_audit") == 3
    assert (await _as(client, users["cs1"]).get("/api/college/students")).status_code == 403  # students never


async def test_job_to_proposals_to_placed(client, monkeypatch):
    org, users = await _college()
    monkeypatch.setattr(pc, "PROPOSE_MIN", 0.0)  # offline embeddings in tests score low; the funnel is what's tested
    tpo = _as(client, users["tpo"])
    jd = "Backend intern. Requirements: Python, FastAPI, PostgreSQL, SQL, Docker. Build APIs for our payments team."
    r = (await tpo.post("/api/college/jobs", json={"title": "Backend Intern", "company": "Zeta", "description": jd, "url": "https://zeta.tech/careers/1"})).json()
    assert r["proposed"] == 2  # the two sharing students; PRIVATE is never proposed
    board = (await tpo.get("/api/college/pipeline?stage=proposed")).json()
    items = {i["student"]: i for i in board["items"]}
    assert set(items) == {"CS1", "MECH1"} and items["CS1"]["reasoning"].get("skills") is not None
    # The HOD (computer) sees only their department's proposal; a teacher can't approve.
    hod_items = (await _as(client, users["hodcs"]).get("/api/college/pipeline?stage=proposed")).json()["items"]
    assert [i["student"] for i in hod_items] == ["CS1"]
    assert (await _as(client, users["teacher"]).post(f"/api/college/placements/{items['MECH1']['id']}/decision", json={"decision": "approve"})).status_code == 403
    # Approve CS1, reject MECH1.
    ok = (await _as(client, users["hodcs"]).post(f"/api/college/placements/{items['CS1']['id']}/decision", json={"decision": "approve", "note": "Register by Friday"})).json()
    assert ok["stage"] == "shortlisted"
    tpo = _as(client, users["tpo"])  # the client is shared: switch back to the TPO
    assert (await tpo.post(f"/api/college/placements/{items['MECH1']['id']}/decision", json={"decision": "reject"})).json()["stage"] == "dismissed"
    assert (await tpo.post(f"/api/college/placements/{items['CS1']['id']}/decision", json={"decision": "reject"})).status_code == 409
    async with session_scope() as s:
        m = (await s.execute(select(JobMatch).where(JobMatch.user_id == users["cs1"].id))).unique().scalar_one()
        assert m.stage == "shortlisted"
        assert (await s.execute(select(Notification).where(Notification.user_id == users["cs1"].id, Notification.kind == "campus"))).scalars().first()
    # Rounds to placed; the student sees it, the job's match records the offer.
    for st in ("round_1", "technical", "hr", "placed"):
        assert (await tpo.put(f"/api/college/placements/{items['CS1']['id']}/stage", json={"stage": st})).json()["stage"] == st
    mine = (await _as(client, users["cs1"]).get("/api/campus/placements")).json()
    assert [p["stage"] for p in mine] == ["placed"] and len(mine[0]["history"]) == 6
    async with session_scope() as s:
        assert (await s.execute(select(JobMatch.outcome).where(JobMatch.user_id == users["cs1"].id))).scalar_one() == "offer"
    prec = (await _as(client, users["tpo"]).get("/api/college/pipeline")).json()["precision"]
    assert prec["decided"] == 2 and prec["approved"] == 1 and prec["precision"] == 0.5
    # The college's job is for its own students only.
    from app.agents.scout import shared_candidates
    from app.schemas import Preferences

    async with session_scope() as s:
        outsider = User(email="other@iit.example", name="O", password_hash="x", adult_confirmed_at=datetime.now(UTC))
        s.add(outsider)
        await s.flush()
        job = (await s.execute(select(Job).where(Job.org_id == org.id))).scalar_one()
        vec = list(job.embedding)
    seen_out = await shared_candidates(outsider.id, Preferences(), vec, None, datetime.now(UTC))
    seen_in = await shared_candidates(users["cs1"].id, Preferences(), vec, None, datetime.now(UTC))
    assert job.id not in {j.id for j in seen_out}
    assert seen_in is not None


async def test_proposals_from_students_own_matches(client):
    org, users = await _college()
    async with session_scope() as s:
        j = Job(source="t", external_id="x1", company="Acme", title="Data Intern")
        s.add(j)
        await s.flush()
        s.add(JobMatch(user_id=users["cs1"].id, job_id=j.id, score=82, strengths=["Python"], gaps=["Spark"], explanation="Strong: Python."))
        s.add(JobMatch(user_id=users["private"].id, job_id=j.id, score=90))
    r = (await _as(client, users["tpo"]).post("/api/college/proposals/refresh")).json()
    assert r["proposed"] == 1  # the private student's match is never proposed
    async with session_scope() as s:
        cp = (await s.execute(select(CampusPlacement))).scalar_one()
        assert cp.user_id == users["cs1"].id and cp.reasoning["gaps"] == ["Spark"]


async def test_campus_lead_and_skill_families(client):
    r = await client.post("/api/campus/leads", json={"college": "GCOE Pune", "name": "Prof. Rao", "email": "tpo@gcoe.ac.in", "role": "TPO", "students": 600, "plan": "institution"})
    assert r.status_code == 201
    assert (await client.post("/api/campus/leads", json={"college": "X", "name": "Y", "email": "bad"})).status_code == 422
    assert adjacent(["PyTorch", "PostgreSQL"], ["TensorFlow", "MySQL", "Go"]) == [("TensorFlow", "PyTorch"), ("MySQL", "PostgreSQL")]
    _, _, cov = skill_overlap(["PyTorch"], ["TensorFlow"])
    assert 50 < cov < 70  # a close substitute earns partial credit, not full

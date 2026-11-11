"""Industry-wise ATS scoring, the original-vs-tailored comparison, the resume builder's files, and mock interview
rounds with strict-mode integrity checks."""

import pytest
from sqlalchemy import select, update

from app.db import session_scope
from app.models import Job, JobMatch, Profile, TailoredResume, User
from app.schemas import ResumeData
from app.services import ats
from app.services.interview_rounds import ROUNDS, build_rounds

STRONG = ResumeData(
    name="Asha Rao",
    email="asha.rao@gmail.com",
    phone="+91 98765 43210",
    links=["linkedin.com/in/asharao", "github.com/asharao"],
    summary="Final-year CSE student building backend services in Python and FastAPI, with an internship shipping REST APIs and PostgreSQL schemas.",
    skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Git", "REST APIs", "React", "Data Structures & Algorithms", "Linux", "SQL"],
    experience=[
        {
            "title": "Backend Intern",
            "organization": "Zeta",
            "start": "May 2025",
            "end": "Jul 2025",
            "bullets": [
                "Built 6 REST APIs in FastAPI serving 12k daily requests with p95 latency under 120 ms",
                "Reduced PostgreSQL query time by 40% by adding indexes and rewriting 5 slow joins",
                "Containerised the service with Docker and set up CI, cutting deploy time from 20 to 4 minutes",
            ],
        }
    ],
    projects=[{"name": "Campus Eats", "tech": ["React", "Node.js"], "bullets": ["Developed a food-ordering app used by 800 students with React and Node.js", "Wrote 60 unit tests with Jest"]}],
    education=[{"school": "PES University", "degree": "B.Tech CSE", "start": "2022", "end": "2026", "details": "CGPA 8.6"}],
)
WEAK = ResumeData(
    name="Ravi",
    email="ravi@gmail.com",
    skills=["Python", "MS Office"],
    projects=[{"name": "Website", "bullets": ["Responsible for making website", "Worked on frontend and backend of the project for college", "Helped team in testing"]}],
    education=[{"school": "XYZ College", "degree": "BCA"}],
)
JD_TITLE = "Backend Developer Intern"
JD = """About the role
Requirements:
- Strong Python and SQL skills; experience with FastAPI or Django
- Must know REST APIs, Git and Docker
- Understanding of data structures and algorithms
Nice to have: AWS, Redis, Kubernetes
Good communication and teamwork."""


def test_strong_resume_outscores_weak_in_every_mode():
    for title, jd in (("", ""), (JD_TITLE, JD)):
        s = ats.score(ats.view_from_resume(STRONG), None, title, jd)
        w = ats.score(ats.view_from_resume(WEAK), None, title, jd)
        assert s["score"] >= 80 > 45 >= w["score"]
        assert s["grade"] in ("Excellent", "Good") and w["grade"] == "Needs work"
        assert abs(sum(b["points"] for b in s["breakdown"]) - s["score"]) <= 1


def test_same_resume_same_score():
    a = ats.score(ats.view_from_resume(STRONG), None, JD_TITLE, JD)
    b = ats.score(ats.view_from_resume(STRONG), None, JD_TITLE, JD)
    assert a == b


def test_job_keywords_are_weighted_and_alternatives_count():
    kws = {k.term: k for k in ats.jd_keywords(JD_TITLE, JD, "software")}
    assert kws["Python"].importance == "required" and kws["AWS"].importance == "preferred"
    assert kws["Python"].weight > kws["AWS"].weight
    assert kws["Django"].alternatives == {"FastAPI"}
    report = ats.score(ats.view_from_resume(STRONG), None, JD_TITLE, JD)
    missing = [m["term"] for m in report["keywords"]["missing"]]
    assert "Django" not in missing  # FastAPI satisfies "FastAPI or Django"
    assert "AWS" in missing and "Kubernetes" in missing


def test_missing_required_keyword_costs_more_than_a_nice_to_have():
    base = ats.score(ats.view_from_resume(STRONG), None, JD_TITLE, JD)["score"]
    no_docker = STRONG.model_copy(deep=True)
    no_docker.skills.remove("Docker")
    no_docker.experience[0].bullets[2] = "Set up CI, cutting deploy time from 20 to 4 minutes"
    with_aws = STRONG.model_copy(deep=True)
    with_aws.skills.append("AWS")
    assert ats.score(ats.view_from_resume(no_docker), None, JD_TITLE, JD)["score"] < base
    assert ats.score(ats.view_from_resume(with_aws), None, JD_TITLE, JD)["score"] >= base


def test_a_skill_shown_in_a_bullet_counts_more_than_one_only_listed():
    listed = STRONG.model_copy(deep=True)
    listed.experience[0].bullets[2] = "Set up CI, cutting deploy time from 20 to 4 minutes"  # Docker only in Skills now
    a = ats.score(ats.view_from_resume(STRONG), None, JD_TITLE, JD)
    b = ats.score(ats.view_from_resume(listed), None, JD_TITLE, JD)
    assert "Docker" in b["keywords"]["listed_only"] and "Docker" not in a["keywords"]["listed_only"]
    assert b["breakdown"][0]["score"] < a["breakdown"][0]["score"]


def test_unreadable_upload_is_capped_and_explained():
    v = ats.view_from_resume(STRONG, raw_text="Asha", filename="resume.pdf")
    r = ats.score(v)
    assert r["score"] <= 25
    assert r["improvements"][0]["title"].startswith("Text can be read")


def test_parse_checks_catch_columns_icons_and_missing_contact():
    raw = "\n".join(["Asha Rao    ★ Skills        ✉ asha@x.com"] * 10 + ["Python    Experience    React"] * 10 + ["word " * 40] * 8)
    r = ats.score(ats.view_from_resume(ResumeData(name="Asha", skills=["Python"]), raw_text=raw, filename="r.png"))
    by = {c["id"]: c["status"] for c in r["checks"]}
    assert by["columns"] == "warn" and by["symbols"] == "warn" and by["filetype"] == "warn" and by["phone"] == "fail"


@pytest.mark.parametrize(
    ("title", "industry"),
    [
        ("UI/UX Design Intern", "design"),
        ("Data Analyst Intern", "data_analytics"),
        ("ML Engineer Intern", "data_science"),
        ("SDE Intern", "software"),
        ("Business Development Associate", "sales"),
        ("HR Intern - Talent Acquisition", "hr"),
        ("Digital Marketing Intern", "marketing"),
        ("Finance Intern", "finance"),
        ("Mechanical Design Engineer Trainee", "core_engineering"),
        ("Supply Chain Intern", "operations"),
        ("Associate Product Manager Intern", "product"),
        ("Strategy Consulting Intern", "consulting"),
    ],
)
def test_industry_detection_from_title(title, industry):
    assert ats.detect_industry(title)[0] == industry


def test_industry_rules_differ_design_needs_a_portfolio():
    designer = ResumeData(name="Mira", email="m@x.com", phone="9876543210", summary="UI/UX designer focused on research-led mobile design for fintech and edtech products.", skills=["Figma", "User research", "Wireframing", "Prototyping", "Design systems", "Usability testing"], projects=[{"name": "PayEasy", "bullets": ["Designed a UPI onboarding flow in Figma; usability testing with 12 users cut drop-off by 30%"]}], education=[{"school": "NID", "degree": "B.Des"}])
    r = ats.score(ats.view_from_resume(designer), "design")
    proof = next(c for c in r["checks"] if c["id"] == "proof_link")
    assert proof["status"] == "fail"
    designer.links.append("behance.net/mira")
    assert ats.score(ats.view_from_resume(designer), "design")["score"] > r["score"]


def test_weak_bullets_get_suggestions_without_invented_numbers():
    r = ats.score(ats.view_from_resume(WEAK))
    assert r["weak_bullets"]
    for b in r["weak_bullets"]:
        assert b["suggestion"]
        assert not any(ch.isdigit() for ch in b["suggestion"].replace("[N]", "").replace("[X]", ""))


# ---------------------------------------------------------------- API


async def _job_match(resume: ResumeData, title=JD_TITLE, jd=JD, skills=("Python", "SQL", "FastAPI", "Docker")) -> str:
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(resume=resume.model_dump(), resume_text="", resume_filename="resume.pdf"))
        j = Job(source="t", external_id=f"a{title}", company="Zeta", title=title, description=jd, skills=list(skills))
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=70.0, semantic_score=70, skill_score=60, strengths=["Python"], gaps=[])
        s.add(m)
        await s.flush()
        return str(m.id)


async def test_score_api_saved_resume_draft_and_match(authed):
    assert (await authed.post("/api/ats/score", json={})).status_code == 409
    mid = await _job_match(WEAK)
    saved = (await authed.post("/api/ats/score", json={})).json()
    draft = (await authed.post("/api/ats/score", json={"resume": STRONG.model_dump()})).json()
    assert draft["score"] > saved["score"]
    job = (await authed.post("/api/ats/score", json={"match_id": mid})).json()
    assert job["mode"] == "job" and job["industry"] == "software" and job["gaps"]
    assert {i["key"] for i in (await authed.get("/api/ats/industries")).json()} >= {"software", "design", "finance"}


async def test_compare_original_and_tailored(authed):
    mid = await _job_match(STRONG)
    async with session_scope() as s:
        s.add(TailoredResume(match_id=mid, model="t", guard_report={"passed": True}, bullets=[
            {"source_id": "exp0.b2", "original": STRONG.experience[0].bullets[2], "rewritten": "Containerised the FastAPI service with Docker and set up CI, cutting deploy time from 20 to 4 minutes", "keywords": ["Docker"], "reverted": False, "source_refs": [{"id": "exp0.b2", "label": "Backend Intern"}]},
            {"source_id": "proj0.b1", "original": "Wrote 60 unit tests with Jest", "rewritten": "Wrote 60 unit tests with Jest and Kubernetes", "keywords": [], "reverted": True, "revert_reason": "Adds Kubernetes", "source_refs": []},
        ]))
    out = (await authed.get(f"/api/matches/{mid}/ats-compare")).json()
    assert out["tailored_ready"] and out["original"]["score"] > 0 and out["tailored"]["score"] > 0
    assert out["delta"] == out["tailored"]["score"] - out["original"]["score"]
    assert out["delta"] >= 0  # rephrasing and reordering never makes the ATS score worse
    changed = [b for b in out["bullets"] if b["changed"]]
    assert len(changed) == 1 and changed[0]["source_id"] == "exp0.b2"
    assert any(b["reverted"] for b in out["bullets"])
    assert out["skills"]["tailored_first"][0] in ("Python", "FastAPI", "Docker", "SQL")


async def test_builder_renders_ats_friendly_files(authed):
    pdf = await authed.post("/api/resume/render?format=pdf", json=STRONG.model_dump())
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    docx = await authed.post("/api/resume/render?format=docx", json=STRONG.model_dump())
    assert docx.status_code == 200 and docx.content[:2] == b"PK"


async def test_improve_bullet_offline_gives_rules_not_inventions(authed):
    r = (await authed.post("/api/resume/improve-bullet", json={"text": "Responsible for making website for college fest"})).json()
    assert any(i.startswith("weak opener") for i in r["issues"]) and "no measurable result" in r["issues"]
    assert r["tip"] and r["options"] == []  # offline mode: no AI rewrites, only the rule-based tip


# ---------------------------------------------------------------- interview rounds + integrity


def test_every_industry_has_real_rounds():
    for key, rounds in ROUNDS.items():
        kinds = [r.kind for r in rounds]
        assert kinds[0] == "screening" and kinds[-1] == "behavioural", key
        assert len(rounds) >= 3
        rs, qs, ind = build_rounds(key, "Intern", "Acme", [], None, ["My project"])
        assert ind == key and 5 <= len(qs) <= 16
        assert {q["round"] for q in qs} == set(range(len(rs)))
        assert all(q["q"] and q["jd_line"] for q in qs)


def test_retakes_rotate_bank_questions():
    a = [q["q"] for q in build_rounds("software", "SDE Intern", "Acme", [], None, [], seed=0)[1]]
    b = [q["q"] for q in build_rounds("software", "SDE Intern", "Acme", [], None, [], seed=1)[1]]
    assert a != b


async def test_interview_v2_rounds_interviewer_and_report(authed):
    mid = await _job_match(STRONG)
    s = (await authed.post("/api/interviews", json={"match_id": mid, "interviewer": "male", "strict": True})).json()
    assert s["meta"]["interviewer"] == "male" and s["meta"]["industry"] == "software" and s["status"] == "active"
    assert [r["kind"] for r in s["rounds"]][0] == "screening"
    q = next(q for q in s["questions"] if q["round_name"].startswith("Technical"))
    assert any(r["kind"] == "coding" for r in s["rounds"]) and s["meta"]["minutes"] == 45 and s["meta"]["level"] in ("intern", "fresher")
    good = f"I worked on this in my internship: I used {q.get('skill') or ''} with {', '.join(q['key_points'])} and I built a service that reduced latency by 40%, which the team adopted, so the result was measurable."
    out = (await authed.post(f"/api/interviews/{s['id']}/answer", json={"question_id": q["id"], "answer": good, "meta": {"mode": "typed", "keystrokes": len(good) + 20, "active_ms": 90000}})).json()
    assert out["scores"][q["id"]]["score"] >= 3 and not out["scores"][q["id"]].get("integrity_flags")
    assert out["rounds"][q["round"]]["answered"] == 1


async def test_pasted_answers_dont_count_in_strict_mode(authed):
    mid = await _job_match(STRONG)
    s = (await authed.post("/api/interviews", json={"match_id": mid, "strict": True})).json()
    q = s["questions"][2]
    text = "I used a hash set: I scanned the array once and checked the set before inserting, which is O(n) time and O(n) space, and sorting is O(n log n)."
    out = (await authed.post(f"/api/interviews/{s['id']}/answer", json={"question_id": q["id"], "answer": text, "meta": {"mode": "typed", "keystrokes": 3, "active_ms": 2000}})).json()
    sc = out["scores"][q["id"]]
    assert sc["integrity_flags"] and sc["score"] <= 1.5
    assert q["id"] in out["integrity"]["flagged_answers"]
    # Practice mode (not strict) doesn't police the answer box.
    s2 = (await authed.post("/api/interviews", json={"match_id": mid, "strict": False})).json()
    out2 = (await authed.post(f"/api/interviews/{s2['id']}/answer", json={"question_id": s2["questions"][2]["id"], "answer": text, "meta": {"mode": "typed", "keystrokes": 3, "active_ms": 2000}})).json()
    assert not out2["scores"][s2["questions"][2]["id"]].get("integrity_flags")


async def test_leaving_three_times_ends_a_strict_interview(authed):
    mid = await _job_match(STRONG)
    s = (await authed.post("/api/interviews", json={"match_id": mid, "strict": True})).json()
    sid = s["id"]
    for t in ("paste_blocked", "tab_hidden", "fullscreen_exit"):
        r = (await authed.post(f"/api/interviews/{sid}/integrity", json={"type": t})).json()
        assert r["status"] == "active"
    assert r["integrity"]["violations"] == 2 and r["integrity"]["counts"]["paste_blocked"] == 1
    r = (await authed.post(f"/api/interviews/{sid}/integrity", json={"type": "window_blur"})).json()
    assert r["status"] == "terminated" and r["integrity"]["terminated_reason"]
    blocked = await authed.post(f"/api/interviews/{sid}/answer", json={"question_id": s["questions"][0]["id"], "answer": "Hello"})
    assert blocked.status_code == 409
    assert (await authed.post(f"/api/interviews/{sid}/integrity", json={"type": "bogus"})).status_code == 422

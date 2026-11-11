"""Coding rounds with the AI code reviewer, interview lengths and levels, trend-refreshed questions, and the
end-of-interview report graded against each field's norms."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db import session_scope
from app.models import Job, JobMatch, Profile, TrendQuestion, User
from app.services import code_review, question_trends
from app.services.interview_rounds import build_plan, level_of

JD = """Requirements:
- Strong Python and SQL; experience with FastAPI or Django
- Must know REST APIs, Git and Docker
- Understanding of data structures and algorithms"""


async def _match(title="Backend Developer Intern", jd=JD) -> str:
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(resume={"name": "Asha", "skills": ["Python"], "projects": [{"name": "Campus Eats", "bullets": ["Built it"]}]}))
        j = Job(source="t", external_id=title, company="Zeta", title=title, description=jd, skills=["Python"])
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=70.0, semantic_score=70, skill_score=60, strengths=["Python"], gaps=[])
        s.add(m)
        await s.flush()
        return str(m.id)


def test_lengths_and_levels():
    assert level_of("SDE Intern") == "intern" and level_of("Graduate Engineer Trainee") == "fresher" and level_of("Analyst") == "fresher"
    for minutes in (30, 45, 60):
        rounds, qs, key, level = build_plan("software", "SDE Intern", "Acme", [], None, ["P"], minutes)
        total = sum(q["seconds"] + (0 if q["kind"] == "coding" else 60) for q in qs) / 60
        assert abs(total - minutes) <= minutes * 0.2, (minutes, total)
        coding = [q for q in qs if q["kind"] == "coding"]
        assert coding and all(q["problem"]["tests"] for q in coding)
        assert all(r["norm"] for r in rounds)
    assert len([q for q in build_plan("software", "SDE Intern", "A", [], None, [], 60)[1]]) > len(build_plan("software", "SDE Intern", "A", [], None, [], 30)[1])
    # Non-technical fields have no coding round.
    assert not any(r["kind"] == "coding" for r in build_plan("marketing", "Marketing Intern", "A", [], None, [], 45)[0])


async def test_baseline_trends_load_and_feed_interviews(authed):
    assert await question_trends.ensure_baseline() > 10
    assert await question_trends.ensure_baseline() == 0  # idempotent
    qs = await question_trends.trend_questions("data_science", 3)
    assert len(qs) == 3 and all(q["label"].startswith("Current topic") for q in qs)
    mid = await _match("Machine Learning Intern", "Requirements: Python, PyTorch, LLMs and RAG experience.")
    s = (await authed.post("/api/interviews", json={"match_id": mid, "minutes": 60})).json()
    assert s["meta"]["industry"] == "data_science" and any(q.get("trend") for q in s["questions"])
    t = (await authed.get("/api/interviews/trends/data_science")).json()
    assert t["source"] == "baseline" and t["skills"] and t["questions"]


def test_trends_are_measured_from_postings():
    now = [("Machine Learning Intern", "Build RAG pipelines with LLMs and a vector database", ["Python"]) for _ in range(30)]
    before = [("Machine Learning Intern", "Train scikit-learn models in Python", ["Python"]) for _ in range(30)]
    out = question_trends.measure(now, before)["data_science"]
    rag = next(r for r in out["skills"] if r["skill"] == "RAG")
    assert rag["share"] == 1.0 and rag["previous"] == 0 and rag["growth"] > 0
    # No earlier window: demand is measured but growth is unknown, not "+100%".
    alone = question_trends.measure(now, [])["data_science"]
    assert all(r["growth"] is None for r in alone["skills"])
    assert out["skills"][0]["skill"] in ("RAG", "LLMs", "Vector Databases")


async def test_refresh_writes_questions_for_rising_skills(authed):
    async with session_scope() as s:
        old = datetime.now(UTC) - timedelta(days=40)
        for i in range(25):
            s.add(Job(source="t", external_id=f"n{i}", company="X", title="Machine Learning Intern", description="Build RAG pipelines with LLMs, embeddings and a vector database.", skills=["Python"]))
        for i in range(25):
            s.add(Job(source="t", external_id=f"o{i}", company="X", title="Machine Learning Intern", description="Train scikit-learn models.", skills=["Python"], fetched_at=old))
    out = await question_trends.refresh()
    assert out["questions"] >= 1
    async with session_scope() as s:
        fresh = (await s.execute(select(TrendQuestion).where(TrendQuestion.source != "baseline"))).scalars().all()
    assert fresh and all(q.industry == "data_science" for q in fresh)
    qs = await question_trends.trend_questions("data_science", 2)
    assert qs[0]["label"].startswith(("Rising in postings", "In demand in recent postings"))
    assert (await authed.post("/api/admin/trends/refresh")).status_code == 403  # admins only


def test_review_tests_decide_correctness():
    sol = "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n"
    ok = code_review._clamp_to_tests(code_review.offline_review(code_review.BY_ID["two_sum"], "python", sol, "Hash map, O(n) time and O(n) space, one pass.", {"ran": True, "passed": 5, "total": 5}), {"ran": True, "passed": 5, "total": 5}, "python")
    assert ok["verdict"] == "correct" and ok["efficiency"] >= 4
    slow = "def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] + nums[j] == target:\n                return [i, j]\n"
    r = code_review.offline_review(code_review.BY_ID["two_sum"], "python", slow, "", {"ran": True, "passed": 5, "total": 5})
    assert r["efficiency"] <= 2 and any("nested" in i for i in r["improvements"])
    # An AI verdict can't contradict tests that ran.
    claimed = {"verdict": "correct", "correctness": 5}
    assert code_review._clamp_to_tests(dict(claimed), {"ran": True, "passed": 2, "total": 5}, "python")["verdict"] == "partially correct"
    assert code_review._clamp_to_tests({"verdict": "incorrect", "correctness": 1}, {"ran": True, "passed": 5, "total": 5}, "python")["verdict"] == "correct"
    assert code_review._clamp_to_tests(dict(claimed), {"ran": False}, "java").get("verified") is False


async def test_coding_submission_and_report(authed):
    mid = await _match()
    s = (await authed.post("/api/interviews", json={"match_id": mid, "minutes": 30, "strict": True})).json()
    assert (await authed.post(f"/api/interviews/{s['id']}/start")).json()["started_at"]
    cq = next(q for q in s["questions"] if q["kind"] == "coding")
    p = cq["problem"]
    assert p["starter"]["python"].startswith(f"def {p['fn']['python']}") and any(t["visible"] for t in p["tests"])
    code = p["starter"]["python"].replace("pass", "return None") + "\n# my attempt\n"
    typed = {"mode": "typed", "keystrokes": len(code) + 10, "active_ms": 600000}
    out = (await authed.post(f"/api/interviews/{s['id']}/code", json={"question_id": cq["id"], "language": "python", "code": code, "approach": "Brute force first.", "results": {"ran": True, "passed": 1, "total": len(p["tests"]), "failures": [{"args": p["tests"][0]["args"], "expected": p["tests"][0]["expected"], "got": None}]}, "meta": typed})).json()
    rv = out["scores"][cq["id"]]
    assert rv["verdict"] == "partially correct" and rv["tests"]["ran"] and rv["tests_label"].startswith("1/")
    # Pasted code in strict mode doesn't count.
    s2 = (await authed.post("/api/interviews", json={"match_id": mid, "minutes": 30, "strict": True})).json()
    cq2 = next(q for q in s2["questions"] if q["kind"] == "coding")
    out2 = (await authed.post(f"/api/interviews/{s2['id']}/code", json={"question_id": cq2["id"], "language": "javascript", "code": "function x(a){ return a.map(v => v * 2).filter(Boolean).reduce((p, c) => p + c, 0) }", "results": {"ran": True, "passed": 3, "total": 3}, "meta": {"mode": "typed", "keystrokes": 2, "active_ms": 1000}})).json()
    assert out2["scores"][cq2["id"]]["integrity_flags"]
    # Non-coding questions can't be submitted as code.
    other = next(q for q in s["questions"] if q["kind"] != "coding")
    assert (await authed.post(f"/api/interviews/{s['id']}/code", json={"question_id": other["id"], "language": "python", "code": "x"})).status_code == 404

    for q in s["questions"]:
        if q["kind"] != "coding":
            await authed.post(f"/api/interviews/{s['id']}/answer", json={"question_id": q["id"], "answer": "I like it."})
    rep = (await authed.get(f"/api/interviews/{s['id']}/report")).json()
    assert rep["signal"] in ("Leaning Hire", "No Hire", "Strong No Hire") and rep["panel"]["attributes"] and rep["bar"] in (3.2, 3.6) and rep["minutes"] == 30
    assert all(r["norm"] and r["improvements"] for r in rep["rounds"])
    coding = next(r for r in rep["rounds"] if r["kind"] == "coding")
    assert coding["coding"][0]["verdict"] == "partially correct" and coding["status"] in ("Below bar", "Meets bar", "Above bar")
    assert any(r["gaps"] for r in rep["rounds"]) and rep["focus"]


def test_blank_submission_scores_the_minimum():
    p = code_review.BY_ID["valid_parentheses"]
    r = code_review.offline_review(p, "python", p.signature("python"), "", {"ran": True, "passed": 0, "total": 7})
    assert r["verdict"] == "incorrect" and r["correctness"] == r["efficiency"] == r["quality"] == r["communication"] == 1

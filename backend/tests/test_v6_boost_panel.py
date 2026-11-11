"""ATS boost toward a target, evidence-checked fit reviews, and the interview panel (follow-ups, coding stages,
rubric retrieval, the evaluator ensemble and five-tier verdicts)."""

from app.agents.matcher import FitReview, Requirement, audit_review
from app.schemas import ExperienceItem, ProjectItem, ResumeData
from app.services.interview_panel import _rule_clarify, process_scores, verdict
from app.services.interview_rubrics import retrieve

RESUME = ResumeData(
    name="Asha",
    email="asha@example.com",
    phone="+91 98765 43210",
    links=["github.com/asha"],
    skills=["Python", "Flask", "PostgreSQL", "SQL", "Git", "REST API"],
    experience=[ExperienceItem(title="Backend Intern", organization="Zeta", start="Jun 2025", end="Aug 2025", bullets=["Worked on the payments API in Flask.", "Wrote SQL reports for the ops team."])],
    projects=[ProjectItem(name="Campus Eats", tech=["Flask", "PostgreSQL"], bullets=["Built a food ordering app for the hostel.", "Designed the orders table and REST API."])],
)


async def test_boost_asks_for_figures_then_uses_them(authed):
    r = (await authed.post("/api/resume/ai-boost", json={"resume": RESUME.model_dump(), "target": 90})).json()
    assert r["target"] == 90 and r["after"] >= r["before"] and r["potential"] >= r["after"]
    asks = {a["id"]: a for a in r["needs_figures"]}
    assert asks and all(a["question"] for a in asks.values())
    sid = next(iter(asks))
    r2 = (await authed.post("/api/resume/ai-boost", json={"resume": r["resume"], "target": 90, "figures": {sid: "used by 300 students", "exp9.b9": "ignored, no such bullet"}})).json()
    assert any("300 students" in c["after"] for c in r2["changes"])
    assert r2["after"] >= r["after"]
    # A figure without a number isn't a measurable result and is ignored.
    r3 = (await authed.post("/api/resume/ai-boost", json={"resume": r["resume"], "figures": {sid: "a lot of people"}})).json()
    assert not any("a lot of people" in c["after"] for c in r3["changes"])


def test_fit_review_needs_real_evidence():
    review = FitReview(
        requirements=[
            Requirement(text="Python", kind="must", status="met", evidence="Built a food ordering app in Python"),
            Requirement(text="Kubernetes", kind="must", status="met", evidence="Deployed services on Kubernetes clusters"),
            Requirement(text="Docker", kind="nice", status="missing"),
        ],
        fit_score=90,
        strengths=[],
        gaps=[],
        explanation="",
    )
    out = audit_review(review, RESUME.model_dump_json() + " built a food ordering app in python")
    k8s = next(r for r in out.requirements if r.text == "Kubernetes")
    assert k8s.status == "missing" and "Kubernetes" in out.gaps and out.fit_score < 90


def test_rubrics_and_verdicts():
    assert [r.id for r in retrieve("coding", "software")][0] == "coding_process"
    assert {r.id for r in retrieve("behavioural")} & {"star", "leadership", "googleyness"}
    assert verdict([{"score": 4}, {"score": 4}, {"score": 4}, {"score": 3}]) == "Strong Hire"
    assert verdict([{"score": 3}, {"score": 3}, {"score": 3}, {"score": 3}]) == "Hire"
    assert verdict([{"score": 3}, {"score": 2}, {"score": 3}, {"score": 3}]) == "Leaning Hire"
    assert verdict([{"score": 1}, {"score": 3}, {"score": 4}, {"score": 3}]) == "No Hire"
    assert verdict([{"score": 1}, {"score": 1}, {"score": 2}, {"score": 2}]) == "Strong No Hire"


def test_coding_process_is_scored():
    none = process_scores({}, "O(n) time")
    assert (none["clarification"], none["design"], none["testing"]) == (1, 1, 1) and len(none["process_feedback"]) == 3
    good = process_scores({"clarifications": [{"q": "Can it be empty?", "a": "Yes"}, {"q": "How large?", "a": "1e5"}], "time_complexity": "O(n)", "space_complexity": "O(n)", "test_notes": "Walked through the empty list and duplicates; could optimise memory with two pointers."}, "O(n) time, O(n) space")
    assert good["clarification"] >= 4 and good["design"] == 5 and good["testing"] >= 4 and not good["process_feedback"]
    assert "empty" in _rule_clarify({"tests": [{"args": [[], 3]}]}, "Can the list be empty?").lower()


async def test_interview_follow_up_clarify_and_panel(authed):
    from tests.test_interview_v3 import _match

    mid = await _match()
    s = (await authed.post("/api/interviews", json={"match_id": mid, "minutes": 30, "strict": False})).json()
    verbal = next(q for q in s["questions"] if q["kind"] != "coding")
    long = "I built Campus Eats with Flask and PostgreSQL for 200 students and designed the orders table and API myself."
    fu = (await authed.post(f"/api/interviews/{s['id']}/follow-up", json={"question_id": verbal["id"], "answer": long})).json()["follow_up"]
    assert fu.endswith("?")
    assert (await authed.post(f"/api/interviews/{s['id']}/follow-up", json={"question_id": verbal["id"], "answer": "Too short."})).json()["follow_up"] == ""
    coding = next(q for q in s["questions"] if q["kind"] == "coding")
    a = (await authed.post(f"/api/interviews/{s['id']}/clarify", json={"question_id": coding["id"], "question": "How large can the input get?"})).json()["answer"]
    assert a and "def " not in a
    p = coding["problem"]
    base = {"question_id": coding["id"], "language": "python", "code": p["starter"]["python"].replace("pass", "return None"), "results": {"ran": True, "passed": 0, "total": len(p["tests"])}}
    rv = (await authed.post(f"/api/interviews/{s['id']}/code", json={**base, "process": {"time_complexity": "", "clarifications": []}})).json()["scores"][coding["id"]]
    assert rv["clarification"] == 1 and rv["design"] == 1 and any("clarifying" in i for i in rv["improvements"])
    for q in s["questions"]:
        if q["kind"] != "coding":
            await authed.post(f"/api/interviews/{s['id']}/answer", json={"question_id": q["id"], "answer": long + f"\n\nFollow-up: {fu}\nMy answer: I'd cut scope.", "meta": {"follow_up": fu}})
    rep = (await authed.get(f"/api/interviews/{s['id']}/report")).json()
    panel = rep["panel"]
    assert panel["verdict"] in ("Strong No Hire", "No Hire", "Leaning Hire", "Hire", "Strong Hire") and rep["signal"] == panel["verdict"]
    assert {a["key"] for a in panel["attributes"]} >= {"rrk"} and all(1 <= a["score"] <= 4 for a in panel["attributes"])
    session = (await authed.get(f"/api/interviews/{s['id']}")).json()
    assert session["scores"][verbal["id"]]["follow_up"] == fu


def test_field_grading_is_role_aware():
    from app.services import ats

    backend = ResumeData(
        name="B", skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Git"],
        projects=[ProjectItem(name="Payments API", tech=["FastAPI", "PostgreSQL"], bullets=["Built a REST API with FastAPI and PostgreSQL serving 2,000 requests a day."])],
    )
    rep = ats.score(ats.view_from_resume(backend), "software")
    assert rep["track"]["key"] == "backend"
    missing = {m["term"] for m in rep["keywords"]["missing"]}
    assert not missing & {"React Native", "Kubernetes", "Next.js", "GraphQL"}  # a backend resume isn't graded on mobile or frontend stacks
    mobile = ResumeData(name="M", skills=["Kotlin", "Android", "Firebase"], projects=[ProjectItem(name="Bus tracker app", tech=["Android", "Kotlin"], bullets=["Built an Android app in Kotlin with Firebase used by 400 students."])])
    assert ats.score(ats.view_from_resume(mobile), "software")["track"]["key"] == "mobile"
    # With a job description, the job's own terms decide (no track).
    assert ats.score(ats.view_from_resume(backend), "software", "Backend Intern", "Python, FastAPI, Redis")["track"] is None


async def test_boost_adds_proven_skills_and_plans_the_rest():
    from app.services.ats_boost import boost, implied_keywords

    r = ResumeData(
        name="A", links=["github.com/a"], skills=["Python", "Flask"],
        education=[__import__("app.schemas", fromlist=["x"]).EducationItem(school="X", degree="B.Tech", details="Coursework: Object Oriented Programming, DBMS")],
        projects=[ProjectItem(name="Notes API", tech=["Flask"], bullets=["Built a Flask API with pytest test cases.", "Implemented a Trie for search."])],
    )
    found = dict(implied_keywords(r, ["REST APIs", "Git", "Unit Testing", "Data Structures & Algorithms", "OOP", "Kubernetes"]))
    assert set(found) == {"REST APIs", "Git", "Unit Testing", "Data Structures & Algorithms", "OOP"}  # never Kubernetes
    out = await boost(r, "software", "", "", [], {}, 90, None)
    assert out["after"] > out["before"] and {c["after"] for c in out["changes"] if c["section"] == "Skills"} >= {"REST APIs", "Git"}
    plan = out["plan"]
    if not out["reached"]:
        assert plan["keywords"] or plan["figures"]
        figs = {f: "used by 150 students" for f in plan["figures"]}
        again = await boost(ResumeData.model_validate(out["resume"]), out["industry"], "", "", plan["keywords"], figs, 90, None)
        assert again["after"] >= min(90, plan["projected"]) - 1  # the plan's projection holds

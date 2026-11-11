"""Prepare-application without AI or bullet symbols, the one-click resume improvement, document layout, speech-to-text."""

import io

from sqlalchemy import select, update

from app.db import session_scope
from app.models import Profile, User
from app.resume_parser import heuristic_parse
from app.schemas import ResumeData
from app.services import resume_doc
from app.services.resume_improve import rule_rewrite

WEAK = ResumeData(
    name="Ravi Kumar",
    email="ravi@gmail.com",
    phone="+91 98765 43210",
    skills=["Python", "MS Office"],
    experience=[{"title": "Web Intern", "organization": "Zeta", "start": "Jun 2025", "end": "Aug 2025", "bullets": ["Responsible for making website for college fest", "Worked on frontend and backend of the project for the client"]}],
    projects=[{"name": "Fest Site", "bullets": ["Helped team in testing the site before launch"]}],
    education=[{"school": "XYZ College", "degree": "BCA", "details": "CGPA 8.1"}],
)


def test_offline_parser_finds_bullets_that_lost_their_symbols():
    text = """Asha Rao
asha@gmail.com | +91 9876543210
EXPERIENCE
Backend Intern | Zeta | May 2025 - Jul 2025
Built 6 REST APIs in FastAPI serving 12k daily requests with low latency
Reduced PostgreSQL query time by 40% by adding indexes to slow joins
PROJECTS
Campus Eats | React, Node.js
 Developed a food ordering app used by 800 students on campus every week
SKILLS
Python, SQL, React"""
    r = heuristic_parse(text)
    e = r.experience[0]
    assert (e.title, e.organization, e.start, e.end) == ("Backend Intern", "Zeta", "May 2025", "Jul 2025") and len(e.bullets) == 2
    assert r.projects[0].name == "Campus Eats" and len(r.projects[0].bullets) == 1


def test_rule_rewrites_keep_facts_and_read_naturally():
    assert rule_rewrite("Responsible for making website for college fest") == "Built website for college fest"
    assert rule_rewrite("Worked on frontend and backend") == "Developed frontend and backend"
    assert rule_rewrite("Involved in organizing the tech fest, etc") == "Organized the tech fest"
    assert rule_rewrite("Reduced load time by 40%") == "Reduced load time by 40%"


async def test_ai_improve_applies_fixes_without_inventing(authed):
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(resume=WEAK.model_dump(), resume_text="", resume_filename="r.pdf"))
    report = (await authed.post("/api/ats/score", json={"industry": "software"})).json()
    missing = [m["term"] for m in report["keywords"]["missing"] if not m["soft"]]
    out = (await authed.post("/api/resume/ai-improve", json={"industry": "software", "confirmed_keywords": missing[:2]})).json()
    new = out["resume"]
    assert out["after"] > out["before"]
    assert all(k in new["skills"] for k in missing[:2])
    assert not any(k in new["skills"] for k in missing[2:])  # never adds what the student didn't confirm
    assert new["summary"] and 15 <= len(new["summary"].split()) <= 90 and "[" not in new["summary"]
    assert new["experience"][0]["bullets"][0] == "Built website for college fest"
    assert {c["section"] for c in out["changes"]} >= {"Skills", "Experience", "Summary"}
    # Nothing is saved until the student saves it.
    assert (await authed.get("/api/profile")).json()["resume"]["summary"] == ""


async def test_prepare_works_for_a_resume_without_bullets(authed):
    """A resume parsed without bullet points used to make Prepare end with nothing (Tailor skipped, so Outreach did)."""
    from tests.test_pipeline import _work

    from app.models import Job, JobMatch

    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        await s.execute(update(Profile).where(Profile.user_id == me.id).values(resume={"name": "Asha Rao", "skills": ["Python", "SQL"], "education": [{"school": "PES", "degree": "B.Tech"}]}, resume_text="Asha Rao Python SQL"))
        j = Job(source="t", external_id="nb", company="Zeta", title="Backend Developer Intern", description="Requirements: Python and SQL.", skills=["Python", "SQL"], url="https://zeta.example/jobs/1")
        s.add(j)
        await s.flush()
        m = JobMatch(user_id=me.id, job_id=j.id, score=40.0, semantic_score=40, skill_score=60, strengths=["Python", "SQL"], gaps=[])
        s.add(m)
        await s.flush()
        mid = str(m.id)
    assert (await authed.post(f"/api/matches/{mid}/prepare")).status_code == 202
    await _work()
    detail = (await authed.get(f"/api/matches/{mid}")).json()
    assert detail["tailored"] is not None and detail["drafts"], "Prepare must produce a tailored resume and a draft"
    body = next(d for d in detail["drafts"] if d["kind"] == "application")["email_body"]
    assert "attached my resume" in body and "Backend Developer Intern" in body
    # The tailored resume opens with a summary aimed at this job, from the resume's own facts.
    assert "Backend Developer Intern" in detail["tailored"]["guard_report"]["summary"]


def test_word_file_is_compact_a4_and_keeps_headings_with_content():
    from docx import Document

    doc = resume_doc.build(WEAK, None)
    d = Document(io.BytesIO(resume_doc.render_docx(doc)))
    sec = d.sections[0]
    assert round(sec.page_width.mm) == 210 and round(sec.page_height.mm) == 297
    assert d.styles["Normal"].paragraph_format.space_after.pt <= 2 and d.styles["Normal"].paragraph_format.line_spacing == 1.0
    heads = [p for p in d.paragraphs if p.text in ("Summary", "Skills", "Work Experience", "Project Work", "Education")]
    assert len(heads) >= 4 and all(p.paragraph_format.keep_with_next for p in heads)
    assert any("CGPA 8.1" in p.text for p in d.paragraphs)  # education details are no longer dropped
    # The sample layout: "Company" with the dates right-aligned, then the role in italics.
    i = next(i for i, p in enumerate(d.paragraphs) if "\tJun 2025 – Aug 2025" in p.text)
    assert d.paragraphs[i].paragraph_format.keep_with_next and d.paragraphs[i + 1].text == "Web Intern" and d.paragraphs[i + 1].runs[0].italic


def test_pdf_keeps_each_role_together():
    from pypdf import PdfReader

    long = WEAK.model_copy(deep=True)
    long.projects = [long.projects[0].model_copy(update={"name": f"Project {i}", "bullets": ["Designed and tested the full ordering flow end to end for the team"] * 4}) for i in range(14)]
    pdf = resume_doc.render_pdf(resume_doc.build(long, None))
    pages = [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]
    assert len(pages) >= 2
    # No page ends with a project title whose bullets start on the next page.
    for text in pages[:-1]:
        last = [ln for ln in text.splitlines() if ln.strip()][-1]
        assert not last.startswith("Project "), last


async def test_speech_to_text_reports_when_not_configured(authed, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "groq_api_key", None)
    assert (await authed.get("/api/stt/status")).json()["enabled"] is False
    r = await authed.post("/api/stt", files={"audio": ("a.webm", b"x" * 2000, "audio/webm")})
    assert r.status_code == 503


def test_transcripts_get_technical_terms_right():
    from app.api.routes.speech import polish, vocabulary

    assert polish("I set up Jithub actions for CI-CD with POSTgreSQL and node js") == "I set up GitHub actions for CI/CD with PostgreSQL and Node.js"
    assert polish("my kpis on power bi") == "my KPIs on Power BI"
    assert "FastAPI" in vocabulary("Tell me about a time you used FastAPI")

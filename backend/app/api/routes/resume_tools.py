"""Resume builder and ATS tools: industry-wise ATS score, gap report, original-vs-tailored comparison, an
ATS-friendly PDF/DOCX of whatever is in the builder, and bullet rewrites that never add facts."""

import uuid
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.guard import check_claim
from app.api.deps import SessionDep, UserDep
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import JobMatch, Profile
from app.schemas import ResumeData
from app.services import ats, resume_doc
from app.services.ratelimit import hit
from app.skills import extract_skills

router = APIRouter(tags=["resume"])


class ScoreIn(BaseModel):
    resume: ResumeData | None = Field(default=None, description="Score this (the builder's draft) instead of your saved resume")
    industry: str | None = None
    match_id: uuid.UUID | None = None
    job_title: str = Field(default="", max_length=300)
    job_description: str = Field(default="", max_length=20000)


async def _profile(session, user_id) -> Profile | None:
    return (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one_or_none()


async def _match(session, user_id, match_id) -> JobMatch:
    m = (
        await session.execute(select(JobMatch).where(JobMatch.id == match_id, JobMatch.user_id == user_id).options(selectinload(JobMatch.tailored)))
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Match not found")
    return m


@router.get("/ats/industries")
async def industries() -> list[dict]:
    return ats.available_industries()


@router.post("/ats/score")
async def score(body: ScoreIn, user: UserDep, session: SessionDep) -> dict:
    """ATS score with the gap report and improvements, for your saved resume or the builder's draft, against a
    field (industry) or one job (a match, or a pasted job description)."""
    if body.resume is not None:
        view = ats.view_from_resume(body.resume)
    else:
        p = await _profile(session, user.id)
        if p is None or not (p.resume or p.resume_text):
            raise HTTPException(409, "Upload your resume first (Settings → Resume), or build one in the Resume builder")
        view = ats.view_from_resume(ResumeData.model_validate(p.resume or {}), p.resume_text or None, p.resume_filename)
    title, desc = body.job_title, body.job_description
    if body.match_id:
        m = await _match(session, user.id, body.match_id)
        title, desc = m.job.title, m.job.description
    report = ats.score(view, body.industry, title, desc)
    if body.match_id:
        report["job"] = {"match_id": str(body.match_id), "title": title}
    return report


@router.get("/matches/{match_id}/ats-compare")
async def compare(match_id: uuid.UUID, user: UserDep, session: SessionDep, industry: str | None = None) -> dict:
    """Your uploaded resume and the version tailored for this job, scored against the same job, with every change."""
    m = await _match(session, user.id, match_id)
    p = await _profile(session, user.id)
    if p is None or not (p.resume or p.resume_text):
        raise HTTPException(409, "Upload your resume first")
    resume = ResumeData.model_validate(p.resume or {})
    original = ats.view_from_resume(resume, p.resume_text or None, p.resume_filename)
    doc = resume_doc.build(resume, m)
    tailored = ats.view_from_doc(doc, resume)
    out = ats.compare(original, tailored, industry, m.job.title, m.job.description)
    bullets = (m.tailored.bullets if m.tailored else []) or []
    out["tailored_ready"] = bool(m.tailored)
    out["job"] = {"match_id": str(m.id), "title": m.job.title, "company": m.job.company}
    out["bullets"] = [
        {
            "source_id": b.get("source_id"),
            "original": b.get("original", ""),
            "rewritten": b.get("rewritten", ""),
            "changed": (b.get("rewritten") or "") != (b.get("original") or "") and not b.get("reverted"),
            "reverted": bool(b.get("reverted")),
            "revert_reason": b.get("revert_reason", ""),
            "declined": bool(b.get("declined")),
            "keywords": b.get("keywords", []),
            "sources": [r.get("label", r.get("id")) if isinstance(r, dict) else r for r in b.get("source_refs", [])],
        }
        for b in bullets
    ]
    out["skills"] = {"original": list(resume.skills), "tailored_first": doc.key_skills, "tailored_rest": doc.other_skills}
    out["sections"] = {"original": ["Experience", "Projects"], "tailored": [name for name, _ in doc.body_sections()]}
    return out


@router.post("/resume/render")
async def render(body: ResumeData, user: UserDep, format: Literal["pdf", "docx"] = "pdf") -> Response:
    """The builder's resume as an ATS-friendly file: one column, standard headings, real text, no tables or icons."""
    doc = resume_doc.build(body, None)
    if format == "pdf":
        content, mime = resume_doc.render_pdf(doc), "application/pdf"
    else:
        content, mime = resume_doc.render_docx(doc), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{resume_doc.filename(doc, format)}"'})


class BulletIn(BaseModel):
    text: str = Field(min_length=3, max_length=600)
    industry: str | None = None
    job_title: str = Field(default="", max_length=300)
    job_description: str = Field(default="", max_length=8000)


class Rewrites(BaseModel):
    options: list[str] = Field(max_length=3)


REWRITE_SYSTEM = """You improve one resume bullet for an applicant tracking system and a recruiter, without inventing anything.
Rules (strict):
- Keep every fact exactly as given. Never add a tool, skill, number, team size, outcome or responsibility that isn't in the bullet.
- Start with a strong past-tense action verb, cut filler ("responsible for", "worked on", "helped"), keep it to one line (under 30 words).
- If the bullet has no measurable result, add ONE placeholder in square brackets for the student to fill in with their real figure,
  e.g. "[X]%", "[N] users", "[N] hours/week". Never write an actual number that isn't in the bullet.
- You may use the job's wording for things the bullet already shows.
Return up to 3 options."""


@router.post("/resume/improve-bullet")
async def improve_bullet(body: BulletIn, user: UserDep, session: SessionDep) -> dict:
    """Rewrites of one bullet. Each AI option passes the same no-fabrication check as the Tailor (no new skills, no
    new numbers); placeholders like [X]% are left for you to fill in with your real figure."""
    await hit("resume_tools", str(user.id))
    issues = ats.bullet_issues(body.text)
    out = {"issues": issues, "tip": ats.bullet_suggestion(body.text, issues), "options": [], "rejected": 0, "ai": False}
    p = await _profile(session, user.id)
    resume_skills = set(ResumeData.model_validate((p.resume if p else None) or {}).skills)
    allowed = set(extract_skills(body.text)) | resume_skills
    try:
        res = await get_llm().structured(
            agent="tailor",
            tier="fast",
            system=REWRITE_SYSTEM,
            prompt=f"Bullet: {body.text}\n" + (f"Target job: {body.job_title}\n{body.job_description[:2500]}" if body.job_title or body.job_description else ""),
            schema=Rewrites,
            ctx=CallContext(user_id=user.id),
            max_tokens=600,
        )
        out["ai"] = True
        for opt in res.options[:3]:
            verdict = check_claim(opt, ["src"], {"src": body.text}, allowed)
            if verdict.ok and opt.strip() and opt.strip() != body.text.strip():
                out["options"].append({"text": opt.strip(), "issues": ats.bullet_issues(opt.replace("[", "").replace("]", ""))})
            else:
                out["rejected"] += 1
    except (LLMUnavailable, LLMOutputError):
        pass
    return out


class ImproveIn(ScoreIn):
    confirmed_keywords: list[str] = Field(default_factory=list, max_length=30, description="Missing keywords the student confirms they have used")


@router.post("/resume/ai-improve")
async def ai_improve(body: ImproveIn, user: UserDep, session: SessionDep) -> dict:
    """Applies the report's fixes to the resume itself: stronger bullets (facts kept), a summary from the resume's own
    facts, confirmed keywords added to Skills, skills ordered by what's searched for. Returns the improved resume and
    every change; nothing is saved until the student saves it."""
    await hit("resume_tools", str(user.id))
    raw, filename = None, None
    if body.resume is not None:
        resume = body.resume
    else:
        p = await _profile(session, user.id)
        if p is None or not (p.resume or p.resume_text):
            raise HTTPException(409, "Upload your resume first, or build one in the Resume builder")
        resume, raw, filename = ResumeData.model_validate(p.resume or {}), p.resume_text or None, p.resume_filename
    title, desc = body.job_title, body.job_description
    if body.match_id:
        m = await _match(session, user.id, body.match_id)
        title, desc = m.job.title, m.job.description
    from app.services.resume_improve import improve

    return await improve(resume, body.industry, title, desc, body.confirmed_keywords, user.id, raw, filename)


@router.post("/resume/restructure")
async def restructure_resume(user: UserDep, session: SessionDep, file: UploadFile | None = File(default=None), industry: str | None = None) -> dict:
    """Your resume rebuilt into a proper structure (contact, summary, grouped skills, roles with title · company ·
    location · dates and their stack, projects, education, certifications) from your own words. Uses the file you
    send, or the resume you uploaded. Returns the structure, what was fixed, and any line that didn't fit, so you can
    check it; nothing is saved until you save it."""
    from app.resume_parser import MAX_RESUME_BYTES, UnsupportedResume, extract_text
    from app.services.resume_improve import write_summary
    from app.services.resume_restructure import restructure

    await hit("resume_tools", str(user.id))
    p = await _profile(session, user.id)
    base = ResumeData.model_validate((p.resume if p else None) or {})
    filename = p.resume_filename if p else None
    if file is not None:
        data = await file.read(MAX_RESUME_BYTES + 1)
        if len(data) > MAX_RESUME_BYTES:
            raise HTTPException(413, "Resume must be under 5 MB")
        try:
            text = extract_text(file.filename or "resume", data)
        except UnsupportedResume as exc:
            raise HTTPException(422, str(exc)) from exc
        filename = file.filename
    elif p is not None and p.resume_text:
        text = p.resume_text
    else:
        raise HTTPException(409, "Upload your resume first (Settings → Resume), or choose a file here")
    from app.resume_parser import heuristic_parse

    # "Before" is the resume as a generic ATS parser reads it.
    before = ats.score(ats.view_from_resume(base if file is None else heuristic_parse(text), text, filename), industry, "", "")
    resume, report = await restructure(text, CallContext(user_id=user.id), base=base if file is None else None)
    field = before["industry"]
    if not resume.summary.strip():
        resume.summary, used = await write_summary(resume, field, "", user.id)
        report["notes"].insert(0, "Added a 2-3 line summary written from your own resume" + (" (AI, checked against your resume)." if used else "."))
        report["sections"].insert(1, "Summary")
    after = ats.score(ats.view_from_resume(resume), field, "", "")
    return {"resume": resume.model_dump(), **report, "before": before["score"], "after": after["score"], "industry": field}


class BoostIn(ImproveIn):
    target: int = Field(default=90, ge=60, le=100)
    figures: dict[str, str] = Field(default_factory=dict, description="bullet id -> the student's real figure for it (e.g. '200 users', '35% faster')")


@router.post("/resume/ai-boost")
async def ai_boost(body: BoostIn, user: UserDep, session: SessionDep) -> dict:
    """Takes the resume toward a target ATS score for its field (default 90): every automatic fix, then the real
    figures the student gives for bullets without results, rewritten in Google's XYZ form. Says how high the score
    goes once the remaining figures are in. Nothing is invented, and nothing is saved until the student saves it."""
    await hit("resume_tools", str(user.id))
    raw, filename = None, None
    if body.resume is not None:
        resume = body.resume
    else:
        p = await _profile(session, user.id)
        if p is None or not (p.resume or p.resume_text):
            raise HTTPException(409, "Upload your resume first, or build one in the Resume builder")
        resume, raw, filename = ResumeData.model_validate(p.resume or {}), p.resume_text or None, p.resume_filename
        from app.services.resume_restructure import looks_broken, restructure

        if raw and looks_broken(resume):  # saved by an older parser in a broken shape: rebuild it from the file
            fixed, _ = await restructure(raw, CallContext(user_id=user.id), base=resume)
            fixed.summary = fixed.summary or resume.summary
            resume = fixed
    title, desc = body.job_title, body.job_description
    if body.match_id:
        m = await _match(session, user.id, body.match_id)
        title, desc = m.job.title, m.job.description
    from app.services.ats_boost import boost

    return await boost(resume, body.industry, title, desc, body.confirmed_keywords, body.figures, body.target, user.id, raw, filename)

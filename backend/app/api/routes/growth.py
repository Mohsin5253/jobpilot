"""JD-specific mock interviews (F9) and the gap-to-proof loop (F10).

Mock interview: 8-12 questions built from the job description's own lines and the student's proof items. Answers
(typed, or spoken and transcribed in the browser) get a rubric score with feedback that quotes the JD line each
question tests. Skills the student shows convincingly can be added to their profile, in their own words, which
re-scores the job (the Interviewer agent's mechanism).

Gap-to-proof: for a near-miss skill gap, a 48-hour mini-project spec. When the student submits a repo, we check on
GitHub's public API that it belongs to their verified account, is recent and actually uses the skill, then add the
skill and re-score the match. The before/after scores are recorded in a run trace.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.matcher import W_SKILLS, W_SKILLS_OFFLINE, level_factor
from app.api.deps import RealUserDep, SessionDep, UserDep
from app.config import settings
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import AgentRun, GapProject, InterviewSession, JobMatch, Profile, RunStatus
from app.schemas import AdditionalSkill, ResumeData
from app.skills import extract_skills, role_digest, skill_overlap

router = APIRouter(tags=["growth"])

_REQ_LINE = re.compile(r"(experience|knowledge|familiar|proficien|understanding|ability|skills?|worked|build|design|develop|analy[sz]e|communicat|team)", re.I)


async def _match(session, user_id, match_id) -> JobMatch:
    m = (await session.execute(select(JobMatch).where(JobMatch.id == match_id, JobMatch.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Match not found")
    return m


async def _profile(session, user_id) -> Profile:
    return (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()


def jd_lines(description: str) -> list[str]:
    lines = [ln.strip(" •-*·\t") for ln in re.split(r"[\n•]|(?<=[.;])\s+", role_digest(description or "", 6000))]
    return [ln for ln in lines if 25 <= len(ln) <= 220 and _REQ_LINE.search(ln)]


def build_questions(title: str, company: str, description: str, evidence: dict | None) -> list[dict]:
    """8-12 questions, each tied to the JD line it tests. Deterministic, so it works without an LLM."""
    qs: list[dict] = []
    seen: set[str] = set()
    for line in jd_lines(description):
        skills = [s for s in extract_skills(line) if s not in seen]
        if skills:
            s = skills[0]
            seen.add(s)
            qs.append({"kind": "skill", "skill": s, "jd_line": line, "q": f"Tell me about a time you used {s}. What did you build, what was hard, and what was the result?"})
        elif len(qs) < 6:
            qs.append({"kind": "situational", "skill": None, "jd_line": line, "q": f"The role asks for this: “{line[:140]}”. How have you shown that, or how would you approach it in your first month?"})
        if len(qs) >= 9:
            break
    for r in ((evidence or {}).get("github") or {}).get("top_repos", [])[:2]:
        if r.get("name"):
            qs.append({"kind": "proof", "skill": r.get("language"), "jd_line": f"Your project: {r['name']}", "q": f"Walk me through {r['name']}: the problem, your design choices, and one thing you'd do differently."})
    generic = [
        {"kind": "motivation", "skill": None, "jd_line": f"{title} at {company}", "q": f"Why this {title} role at {company}, and why now?"},
        {"kind": "behavioural", "skill": None, "jd_line": "Teamwork and ownership (every role)", "q": "Tell me about a time something went wrong in a team project. What did you do?"},
        {"kind": "learning", "skill": None, "jd_line": "Learning fast (every internship)", "q": "What's something technical you taught yourself recently, and how?"},
    ]
    for g in generic:
        if len(qs) >= 12:
            break
        qs.append(g)
    while len(qs) < 8:
        qs.append({"kind": "situational", "skill": None, "jd_line": f"{title} responsibilities", "q": f"Describe how you'd plan your first two weeks as a {title}."})
    return [{**q, "id": f"q{i + 1}"} for i, q in enumerate(qs[:12])]


_ACTION = re.compile(r"\b(i|we)\s+(built|wrote|designed|led|fixed|deployed|analy[sz]ed|reduced|improved|created|implemented|tested|trained|migrated)\b", re.I)
_RESULT = re.compile(r"\b(result|so that|which|reduced|improved|increased|saved|cut|learned|outcome)\b|\d", re.I)


def score_answer(q: dict, answer: str) -> dict:
    """Rubric, 1-5 each: relevance (mentions what the JD line asks for), specificity (concrete actions and figures),
    structure (situation → action → result). Feedback quotes the JD line."""
    a = answer.strip()
    words = len(a.split())
    target = {s.lower() for s in extract_skills(q["jd_line"])} | ({q["skill"].lower()} if q.get("skill") else set())
    mentioned = {s.lower() for s in extract_skills(a)}
    relevance = 5 if target and target & mentioned else 3 if not target and words > 30 else 2 if words > 30 else 1
    specificity = min(5, 1 + bool(_ACTION.search(a)) * 2 + bool(re.search(r"\d", a)) + (words > 60))
    structure = min(5, 1 + bool(_ACTION.search(a)) + bool(_RESULT.search(a)) * 2 + (words > 40))
    total = round((relevance + specificity + structure) / 3, 1)
    tips = []
    if relevance < 4:
        tips.append(f"Tie it to what they asked: “{q['jd_line'][:120]}”" + (f", and name {q['skill']} explicitly." if q.get("skill") else "."))
    if specificity < 4:
        tips.append("Say what you did yourself (“I built…”) and add one number: users, time saved, accuracy.")
    if structure < 4:
        tips.append("Use situation → what you did → the result, in that order.")
    return {"relevance": relevance, "specificity": specificity, "structure": structure, "score": total, "tests": q["jd_line"], "feedback": tips or ["Strong answer: specific, relevant and well structured."]}


class Opinion(BaseModel):
    relevance: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    structure: int = Field(ge=1, le=5)
    feedback: list[str] = Field(max_length=3)


async def grade(q: dict, answer: str, user_id: uuid.UUID) -> dict:
    """The rubric, with an AI grader when available (same rubric; falls back to the rules)."""
    base = score_answer(q, answer)
    try:
        op = await get_llm().structured(
            agent="interviewer", tier="fast", schema=Opinion, ctx=CallContext(user_id=user_id), max_tokens=500,
            system="You grade internship interview answers on a 1-5 rubric: relevance to the job requirement, specificity (own actions, numbers), structure (situation, action, result). Give up to 3 short, kind, concrete tips.",
            prompt=f"Job requirement: {q['jd_line']}\nQuestion: {q['q']}\nAnswer: {answer[:3000]}",
        )
        return {**base, "relevance": op.relevance, "specificity": op.specificity, "structure": op.structure, "score": round((op.relevance + op.specificity + op.structure) / 3, 1), "feedback": op.feedback or base["feedback"]}
    except (LLMUnavailable, LLMOutputError):
        return base


@router.post("/interviews", status_code=201)
async def start_interview(body: dict, user: RealUserDep, session: SessionDep) -> dict:
    m = await _match(session, user.id, body.get("match_id"))
    profile = await _profile(session, user.id)
    sess = InterviewSession(user_id=user.id, application_id=m.id, questions=build_questions(m.job.title, m.job.company, m.job.description, profile.evidence))
    session.add(sess)
    await session.commit()
    return _session_out(sess)


def _session_out(s: InterviewSession) -> dict:
    return {"id": str(s.id), "match_id": str(s.application_id), "questions": s.questions, "answers": s.answers, "scores": s.scores, "completed_at": s.completed_at.isoformat() if s.completed_at else None}


@router.get("/interviews/{session_id}")
async def get_interview(session_id: str, user: UserDep, session: SessionDep) -> dict:
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    return _session_out(s)


class AnswerIn(BaseModel):
    question_id: str
    answer: str = Field(min_length=1, max_length=5000)


@router.post("/interviews/{session_id}/answer")
async def answer(session_id: str, body: AnswerIn, user: RealUserDep, session: SessionDep) -> dict:
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    q = next((q for q in s.questions if q["id"] == body.question_id), None)
    if q is None:
        raise HTTPException(404, "No such question")
    s.answers = {**s.answers, q["id"]: body.answer}
    s.scores = {**s.scores, q["id"]: await grade(q, body.answer, user.id)}
    if len(s.scores) == len(s.questions):
        s.completed_at = s.completed_at or datetime.now(UTC)
    await session.commit()
    return _session_out(s)


class ApplySkills(BaseModel):
    question_ids: list[str] = Field(max_length=12)


def _add_skill(profile: Profile, skill: str, details: str) -> None:
    resume = ResumeData.model_validate(profile.resume or {})
    if skill.lower() not in {x.lower() for x in resume.skills}:
        resume.skills.append(skill)
    resume.additional.append(AdditionalSkill(skill=skill, details=details[:600]))
    profile.resume = resume.model_dump()


@router.post("/interviews/{session_id}/apply-skills")
async def apply_skills(session_id: str, body: ApplySkills, user: RealUserDep, session: SessionDep) -> dict:
    """Adds skills the student showed (score >= 4, in their own words) and re-scores the job."""
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    profile = await _profile(session, user.id)
    added = []
    for qid in body.question_ids:
        q = next((q for q in s.questions if q["id"] == qid), None)
        sc = s.scores.get(qid) or {}
        if q and q.get("skill") and sc.get("score", 0) >= 4 and len(s.answers.get(qid, "").split()) >= 30:
            _add_skill(profile, q["skill"], s.answers[qid])
            added.append(q["skill"])
    if added:
        m = await _match(session, user.id, s.application_id)
        await _rescore(session, profile, m, f"Mock interview: showed {', '.join(added)}")
    await session.commit()
    return {"added": added}


async def _rescore(session, profile: Profile, m: JobMatch, why: str) -> tuple[float, float, AgentRun]:
    """Recomputes the match with the new skills and records before → after as a run trace."""
    resume = ResumeData.model_validate(profile.resume or {})
    before = round(m.score, 1)
    strengths, gaps, skills = skill_overlap(resume.skills, m.job.skills or [])
    # Only the skill component changed: move the score by its weight times the coverage gained.
    weight = W_SKILLS if m.llm_score is not None else W_SKILLS_OFFLINE
    after = round(min(100.0, before + max(0.0, skills - (m.skill_score or 0)) * weight * level_factor(m.job.title, m.job.description)), 1)
    m.skill_score, m.strengths, m.gaps, m.score = skills, strengths, gaps, after
    now = datetime.now(UTC)
    run = AgentRun(
        user_id=profile.user_id, trigger="rescore", status=RunStatus.completed, started_at=now, finished_at=now,
        steps=[
            {"agent": "interviewer", "status": "completed", "started_at": now.isoformat(), "ended_at": now.isoformat(), "detail": why},
            {"agent": "matcher", "status": "completed", "started_at": now.isoformat(), "ended_at": now.isoformat(), "detail": f"Re-scored {m.job.title} at {m.job.company}: {before} → {after}"},
        ],
        stats={"rescore": {"match_id": str(m.id), "before": before, "after": after}},
    )
    session.add(run)
    await session.flush()
    return before, after, run


def project_spec(skill: str, title: str, company: str, jd_line: str) -> dict:
    return {
        "title": f"48-hour {skill} mini-project for {title}",
        "why": f"{company}'s posting asks for {skill}" + (f": “{jd_line[:140]}”" if jd_line else "."),
        "deadline_hours": 48,
        "steps": [
            f"Pick a small, real dataset or problem related to {company}'s product area.",
            f"Build one working piece that uses {skill} end to end (no tutorials copied wholesale).",
            "Write a README: what it does, how to run it, one design decision and one limitation.",
            "Add a test or a short demo (screenshot or GIF).",
            "Push it to a public repo on your verified GitHub account and submit the link here.",
        ],
        "accepted_if": ["The repo is yours and was created or pushed in the last 7 days", f"Its language, topics or README show {skill}"],
    }


@router.get("/matches/{match_id}/gap-projects")
async def gap_projects(match_id: uuid.UUID, user: UserDep, session: SessionDep) -> list[dict]:
    """Proposes (once) a 48-hour project for up to two near-miss gaps of this match."""
    m = await _match(session, user.id, match_id)
    rows = (await session.execute(select(GapProject).where(GapProject.match_id == m.id))).scalars().all()
    if not rows and m.gaps:
        lines = jd_lines(m.job.description)
        for skill in m.gaps[:2]:
            line = next((ln for ln in lines if skill.lower() in ln.lower()), "")
            g = GapProject(user_id=user.id, match_id=m.id, skill=skill, spec=project_spec(skill, m.job.title, m.job.company, line))
            session.add(g)
            rows.append(g)
        await session.commit()
    return [_gap_out(g) for g in rows]


def _gap_out(g: GapProject) -> dict:
    return {"id": str(g.id), "skill": g.skill, "spec": g.spec, "status": g.status, "repo_url": g.repo_url, "before_score": g.before_score, "after_score": g.after_score, "run_id": str(g.run_id) if g.run_id else None}


class RepoIn(BaseModel):
    repo_url: str = Field(max_length=300)


@router.post("/gap-projects/{project_id}/submit")
async def submit_repo(project_id: str, body: RepoIn, user: RealUserDep, session: SessionDep) -> dict:
    g = await session.get(GapProject, project_id)
    if g is None or g.user_id != user.id:
        raise HTTPException(404, "No such project")
    mt = re.match(r"https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", body.repo_url.strip())
    if not mt:
        raise HTTPException(422, "Paste the repo link, like https://github.com/you/project")
    owner, repo = mt.group(1), mt.group(2)
    profile = await _profile(session, user.id)
    gh = (profile.evidence or {}).get("github") or {}
    if not gh.get("verified") or (gh.get("username") or "").lower() != owner.lower():
        raise HTTPException(409, "Verify your GitHub account on the Proof page first; the repo must belong to it")
    headers = {"accept": "application/vnd.github+json", **({"authorization": f"Bearer {settings.github_token}"} if settings.github_token else {})}
    async with httpx.AsyncClient(timeout=15, headers=headers) as c:
        r = await c.get(f"https://api.github.com/repos/{owner}/{repo}")
        if r.status_code != 200:
            raise HTTPException(422, "Couldn't find that public repo on GitHub")
        info = r.json()
        langs = (await c.get(f"https://api.github.com/repos/{owner}/{repo}/languages")).json() if r.status_code == 200 else {}
        readme = await c.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers={"accept": "application/vnd.github.raw"})
    pushed = datetime.fromisoformat(info["pushed_at"].replace("Z", "+00:00")) if info.get("pushed_at") else None
    text = " ".join([*(langs or {}).keys(), info.get("description") or "", " ".join(info.get("topics") or []), readme.text[:20000] if readme.status_code == 200 else ""])
    if (info.get("owner") or {}).get("login", "").lower() != owner.lower() or info.get("fork"):
        raise HTTPException(409, "The repo must be your own, not a fork")
    if not pushed or datetime.now(UTC) - pushed > timedelta(days=7):
        raise HTTPException(409, "The repo hasn't been pushed in the last 7 days")
    if g.skill.lower() not in {s.lower() for s in extract_skills(text)}:
        raise HTTPException(409, f"We couldn't find {g.skill} in the repo's languages, topics or README")
    m = await _match(session, user.id, g.match_id)
    _add_skill(profile, g.skill, f"Built {repo} ({body.repo_url}) in a 48-hour project using {g.skill}.")
    before, after, run = await _rescore(session, profile, m, f"Verified {owner}/{repo}: owned by @{owner}, pushed {pushed:%d %b}, uses {g.skill}")
    g.status, g.repo_url, g.before_score, g.after_score, g.run_id, g.verified_at = "verified", body.repo_url, before, after, run.id, datetime.now(UTC)
    await session.commit()
    return _gap_out(g)

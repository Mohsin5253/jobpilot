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
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agents.matcher import W_SKILLS, W_SKILLS_OFFLINE, level_factor
from app.api.deps import AdminDep, RealUserDep, SessionDep, UserDep
from app.config import settings
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.models import AgentRun, GapProject, InterviewSession, JobMatch, Profile, RunStatus
from app.schemas import AdditionalSkill, ResumeData
from app.ats_lexicon import INDUSTRIES
from app.services import interview_report
from app.services.ats import detect_industry
from app.services.code_review import review as code_review
from app.services.interview_rubrics import as_prompt, retrieve
from app.services.interview_rounds import BAR, build_plan, industry_name
from app.services.question_trends import refresh as refresh_question_trends
from app.services.question_trends import trend_questions, trending_skills
from app.services.ratelimit import hit
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
    points = [p.lower() for p in q.get("key_points") or []]
    if points and not (target and target & mentioned):
        low = a.lower()
        covered = sum(1 for p in points if p in low)
        relevance = max(1, min(5, 1 + round(4 * min(1.0, covered / max(1, 0.6 * len(points))))))
        if words < 12:
            relevance = min(relevance, 2)
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


async def grade(q: dict, answer: str, user_id: uuid.UUID, industry: str = "*") -> dict:
    """The rubric, with an AI grader when available (same rubric; falls back to the rules)."""
    base = score_answer(q, answer)
    try:
        op = await get_llm().structured(
            agent="interviewer", tier="fast", schema=Opinion, ctx=CallContext(user_id=user_id), max_tokens=500,
            system=(
                "You grade interview answers like a trained interviewer at a large tech company, on a 1-5 rubric: relevance to the "
                "job requirement, specificity (own actions, numbers), structure (the right framework for the question). Calibrate "
                "for an intern/fresher. If the answer includes a follow-up exchange, credit how well the candidate adapted. Give up "
                "to 3 short, concrete tips.\nRubrics for this question:\n" + as_prompt(retrieve(q.get("kind") or "behavioural", industry, 3))
            ),
            prompt=f"Job requirement: {q['jd_line']}\nQuestion: {q['q']}\n" + (f"A strong answer covers: {', '.join(q['key_points'])}\n" if q.get("key_points") else "") + f"Answer: {answer[:4000]}",
        )
        return {**base, "relevance": op.relevance, "specificity": op.specificity, "structure": op.structure, "score": round((op.relevance + op.specificity + op.structure) / 3, 1), "feedback": op.feedback or base["feedback"]}
    except (LLMUnavailable, LLMOutputError):
        return base


class StartIn(BaseModel):
    match_id: uuid.UUID
    interviewer: Literal["male", "female"] = "female"
    strict: bool = True
    industry: str | None = None
    minutes: Literal[30, 45, 60] = 45
    level: Literal["intern", "fresher"] | None = None


@router.post("/interviews", status_code=201)
async def start_interview(body: StartIn, user: RealUserDep, session: SessionDep) -> dict:
    """A mock interview for one job, in the rounds that field really uses (screening, technical or case, project,
    HR), asked by the interviewer the student picked. Strict mode turns on integrity checks (see /integrity)."""
    await hit("interview", str(user.id))
    m = await _match(session, user.id, body.match_id)
    profile = await _profile(session, user.id)
    resume = ResumeData.model_validate(profile.resume or {})
    previous = (await session.execute(select(func.count()).select_from(InterviewSession).where(InterviewSession.user_id == user.id, InterviewSession.application_id == m.id))).scalar_one()
    lines = jd_lines(m.job.description)
    industry = body.industry if body.industry in INDUSTRIES else detect_industry(m.job.title, "\n".join(lines))[0]
    trends = await trend_questions(industry, 4, seed=previous)
    hot = [t["skill"] for t in (await trending_skills(industry))["skills"]]
    rounds, questions, industry, level = build_plan(industry, m.job.title, m.job.company, lines, profile.evidence, [p.name for p in resume.projects if p.name], body.minutes, body.level, trends, hot, seed=previous)
    sess = InterviewSession(
        user_id=user.id,
        application_id=m.id,
        questions=questions,
        meta={
            "industry": industry,
            "industry_name": industry_name(industry),
            "interviewer": body.interviewer,
            "strict": body.strict,
            "rounds": rounds,
            "job": {"title": m.job.title, "company": m.job.company},
            "minutes": body.minutes,
            "level": level,
            "bar": BAR[level],
        },
        integrity={"events": [], "violations": 0},
        status="active",
    )
    session.add(sess)
    await session.commit()
    return _session_out(sess)


def _verdict(avg: float | None) -> str:
    if avg is None:
        return "Not finished"
    return "Interview-ready" if avg >= 4 else "Almost there" if avg >= 3.2 else "Needs more practice"


def _session_out(s: InterviewSession) -> dict:
    meta = s.meta or {}
    integ = s.integrity or {}
    rounds = []
    for r in meta.get("rounds", []):
        qids = [q["id"] for q in s.questions if q.get("round") == r["index"]]
        sc = [s.scores[i]["score"] for i in qids if i in s.scores]
        rounds.append({**r, "total": len(qids), "answered": len(sc), "score": round(sum(sc) / len(sc), 1) if sc else None})
    all_sc = [v["score"] for v in s.scores.values()]
    avg = round(sum(all_sc) / len(all_sc), 1) if all_sc else None
    counts: dict[str, int] = {}
    for e in integ.get("events", []):
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    flagged = [qid for qid, v in s.scores.items() if v.get("integrity_flags")]
    return {
        "id": str(s.id),
        "match_id": str(s.application_id),
        "questions": s.questions,
        "answers": s.answers,
        "scores": s.scores,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "status": s.status or "active",
        "meta": meta,
        "rounds": rounds,
        "integrity": {
            "violations": integ.get("violations", 0),
            "max_violations": MAX_VIOLATIONS,
            "counts": counts,
            "flagged_answers": flagged,
            "terminated_reason": integ.get("terminated_reason"),
        },
        "report": {"score": avg, "verdict": _verdict(avg) if s.completed_at else "Not finished", "answered": len(all_sc), "total": len(s.questions)},
        "started_at": meta.get("started_at"),
    }




# Leaving the interview (switching tab or app, leaving full screen) counts against a strict session; the third ends it.
VIOLATIONS = {"tab_hidden", "window_blur", "fullscreen_exit"}
ATTEMPTS = {"paste_blocked", "copy_blocked", "drop_blocked", "shortcut_blocked", "context_menu", "devtools"}
MAX_VIOLATIONS = 3


class IntegrityIn(BaseModel):
    type: Literal["tab_hidden", "window_blur", "fullscreen_exit", "paste_blocked", "copy_blocked", "drop_blocked", "shortcut_blocked", "context_menu", "devtools"]
    question_id: str | None = Field(default=None, max_length=10)


@router.post("/interviews/{session_id}/integrity")
async def integrity(session_id: str, body: IntegrityIn, user: RealUserDep, session: SessionDep) -> dict:
    """Records a proctoring event. In strict mode the third time you leave the interview ends it."""
    s = await session.get(InterviewSession, session_id, with_for_update=True)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    if s.status != "active":
        return _session_out(s)
    integ = dict(s.integrity or {})
    events = list(integ.get("events", []))[-199:]
    events.append({"type": body.type, "q": body.question_id, "at": datetime.now(UTC).isoformat()})
    integ["events"] = events
    if body.type in VIOLATIONS:
        integ["violations"] = integ.get("violations", 0) + 1
        if (s.meta or {}).get("strict") and integ["violations"] >= MAX_VIOLATIONS:
            s.status = "terminated"
            s.completed_at = s.completed_at or datetime.now(UTC)
            integ["terminated_reason"] = f"You left the interview {integ['violations']} times (switched tab or app, or exited full screen). In strict mode the session ends, as a proctored interview would."
    s.integrity = integ
    await session.commit()
    return _session_out(s)


@router.get("/interviews/{session_id}")
async def get_interview(session_id: str, user: UserDep, session: SessionDep) -> dict:
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    return _session_out(s)


class AnswerMeta(BaseModel):
    mode: Literal["typed", "voice", "mixed"] = "typed"
    keystrokes: int = Field(default=0, ge=0, le=100000)
    voice_chars: int = Field(default=0, ge=0, le=20000)
    active_ms: int = Field(default=0, ge=0, le=3_600_000)
    pastes_blocked: int = Field(default=0, ge=0, le=1000)
    follow_up: str | None = Field(default=None, max_length=400, description="The interviewer's follow-up, when one was asked")


class AnswerIn(BaseModel):
    question_id: str
    answer: str = Field(min_length=1, max_length=5000)
    meta: AnswerMeta | None = None


def integrity_flags(answer: str, meta: AnswerMeta | None) -> list[str]:
    """Signs the answer wasn't produced here: text that appeared without keystrokes (pasted or injected), or typing
    faster than a person can. Spoken answers come from the browser's speech recognition and are exempt from the
    keystroke check, but not from the time check."""
    if meta is None:
        return []
    flags = []
    typed = max(0, len(answer) - meta.voice_chars)
    if typed > 40 and meta.keystrokes < 0.6 * typed:
        flags.append("Most of this answer wasn't typed in the answer box")
    secs = meta.active_ms / 1000
    if typed > 60 and secs > 0 and typed / secs > 14:
        flags.append("Typed faster than a person can (over 14 characters a second)")
    if meta.voice_chars > 80 and secs > 0 and len(answer.split()) / secs > 5:
        flags.append("More words than could be spoken in the time")
    return flags


@router.post("/interviews/{session_id}/answer")
async def answer(session_id: str, body: AnswerIn, user: RealUserDep, session: SessionDep) -> dict:
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    if (s.status or "active") == "terminated":
        raise HTTPException(409, "This interview was ended because you left it too many times. Start a new one to try again.")
    q = next((q for q in s.questions if q["id"] == body.question_id), None)
    if q is None:
        raise HTTPException(404, "No such question")
    flags = integrity_flags(body.answer, body.meta) if (s.meta or {}).get("strict", False) else []
    graded = await grade(q, body.answer, user.id, (s.meta or {}).get("industry", "*"))
    if flags:
        # An answer that may not be the student's own can't show they know it.
        graded = {**graded, "score": min(graded["score"], 1.5), "integrity_flags": flags, "feedback": [f"Not counted: {flags[0].lower()}.", *graded["feedback"][:2]]}
    if body.meta:
        graded["mode"] = body.meta.mode
        if body.meta.follow_up:
            graded["follow_up"] = body.meta.follow_up
    s.answers = {**s.answers, q["id"]: body.answer}
    s.scores = {**s.scores, q["id"]: graded}
    if len(s.scores) == len(s.questions):
        s.completed_at = s.completed_at or datetime.now(UTC)
        s.status = "completed"
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
        if q and q.get("skill") and sc.get("score", 0) >= 4 and not sc.get("integrity_flags") and len(s.answers.get(qid, "").split()) >= 30:
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


@router.post("/interviews/{session_id}/start")
async def start_clock(session_id: str, user: RealUserDep, session: SessionDep) -> dict:
    """Starts the interview clock (once), so the report can compare time used with the planned length."""
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    if not (s.meta or {}).get("started_at"):
        s.meta = {**(s.meta or {}), "started_at": datetime.now(UTC).isoformat()}
        await session.commit()
    return _session_out(s)


class TestFailure(BaseModel):
    args: list | dict | str | int | float | None = None
    expected: list | dict | str | int | float | bool | None = None
    got: list | dict | str | int | float | bool | None = None
    error: str | None = Field(default=None, max_length=500)


class TestResults(BaseModel):
    ran: bool = False
    passed: int = Field(default=0, ge=0, le=200)
    total: int = Field(default=0, ge=0, le=200)
    failures: list[TestFailure] = Field(default_factory=list, max_length=20)
    runtime_ms: int = Field(default=0, ge=0, le=600000)


class Clarified(BaseModel):
    q: str = Field(default="", max_length=400)
    a: str = Field(default="", max_length=600)


class CodingProcess(BaseModel):
    """What the candidate did at each stage: clarify → approach & complexity → implement → test & optimise."""

    clarifications: list[Clarified] = Field(default_factory=list, max_length=10)
    time_complexity: str = Field(default="", max_length=60)
    space_complexity: str = Field(default="", max_length=60)
    test_notes: str = Field(default="", max_length=2000)
    stage_ms: dict[str, int] = Field(default_factory=dict)


class CodeIn(BaseModel):
    question_id: str
    language: Literal["python", "javascript", "java", "cpp"]
    code: str = Field(min_length=1, max_length=20000)
    approach: str = Field(default="", max_length=3000)
    results: TestResults = Field(default_factory=TestResults)
    meta: AnswerMeta | None = None
    process: CodingProcess | None = None


@router.post("/interviews/{session_id}/code")
async def submit_code(session_id: str, body: CodeIn, user: RealUserDep, session: SessionDep) -> dict:
    """Submits a coding answer to the AI code reviewer. Test results come from the candidate's browser (code is never
    run on our servers); the reviewer reads the code and can't overrule tests that actually ran."""
    await hit("code_review", str(user.id))
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    if (s.status or "active") == "terminated":
        raise HTTPException(409, "This interview was ended because you left it too many times. Start a new one to try again.")
    q = next((q for q in s.questions if q["id"] == body.question_id), None)
    if q is None or q.get("kind") != "coding":
        raise HTTPException(404, "No such coding question")
    flags = integrity_flags(body.code, body.meta) if (s.meta or {}).get("strict", False) else []
    rv = await code_review(q["problem"]["id"], body.language, body.code, body.approach, body.results.model_dump(), user.id)
    if body.process is not None:
        # The interview process counts, as with a real interviewer: clarify, state complexity, then test.
        from app.services.coding_bank import BY_ID
        from app.services.interview_panel import process_scores

        p = BY_ID.get(q["problem"]["id"])
        ps = process_scores(body.process.model_dump(), p.hint_complexity if p else "")
        rv = {**rv, **{k: v for k, v in ps.items() if k != "process_feedback"}, "process": body.process.model_dump()}
        rv["score"] = round(0.75 * rv["score"] + 0.25 * (ps["clarification"] + ps["design"] + ps["testing"]) / 3, 1)
        rv["improvements"] = [*(rv.get("improvements") or []), *ps["process_feedback"]][:6]
    if flags:
        rv = {**rv, "score": min(rv["score"], 1.5), "integrity_flags": flags, "feedback": [f"Not counted: {flags[0].lower()}.", *rv["feedback"][:2]]}
    rv["tests_visible"] = body.results.total
    s.answers = {**s.answers, q["id"]: body.code + (f"\n\n/* Approach: {body.approach.strip()} */" if body.approach.strip() else "")}
    s.scores = {**s.scores, q["id"]: rv}
    if len(s.scores) == len(s.questions):
        s.completed_at = s.completed_at or datetime.now(UTC)
        s.status = "completed"
    await session.commit()
    return _session_out(s)


async def _report(s: InterviewSession, user, session) -> dict:
    rep = interview_report.build(s)
    # The panel's scorecard (scribe, technical critic, behavioural coach), evaluated once per finished interview.
    panel = (s.meta or {}).get("panel")
    if not panel and s.scores:
        from app.services.interview_panel import evaluate

        panel = await evaluate(s, user.id)
        if s.completed_at:
            s.meta = {**(s.meta or {}), "panel": panel}
            await session.commit()
    if panel:
        rep["panel"] = panel
        rep["signal"] = panel["verdict"]
    if s.completed_at and not (s.meta or {}).get("report_ai") and s.scores:
        ai = await interview_report.narrative(rep, user.id)
        if ai:
            s.meta = {**(s.meta or {}), "report_ai": ai}
            await session.commit()
            rep["summary"], rep["next_week"] = ai["summary"], ai["next_week"]
    started = (s.meta or {}).get("started_at")
    if started and s.completed_at:
        rep["minutes_used"] = round((s.completed_at - datetime.fromisoformat(started)).total_seconds() / 60)
    return rep


class FollowUpIn(BaseModel):
    question_id: str
    answer: str = Field(min_length=1, max_length=5000)


@router.post("/interviews/{session_id}/follow-up")
async def ask_follow_up(session_id: str, body: FollowUpIn, user: RealUserDep, session: SessionDep) -> dict:
    """The interviewer's one follow-up to this answer (pushback, a new constraint, or 'what was your part?'), asked
    before the answer is graded. Empty when the question isn't the kind that gets one."""
    await hit("interview_report", str(user.id))
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    q = next((q for q in s.questions if q["id"] == body.question_id), None)
    if q is None:
        raise HTTPException(404, "No such question")
    from app.services.interview_panel import FOLLOW_UP_KINDS, follow_up

    if q.get("kind") not in FOLLOW_UP_KINDS or len(body.answer.split()) < 12:
        return {"follow_up": ""}
    return {"follow_up": await follow_up(q, body.answer, user.id)}


class ClarifyIn(BaseModel):
    question_id: str
    question: str = Field(min_length=3, max_length=400)


@router.post("/interviews/{session_id}/clarify")
async def clarify_problem(session_id: str, body: ClarifyIn, user: RealUserDep, session: SessionDep) -> dict:
    """The interviewer answers a clarifying question about the coding problem (constraints, edge cases), from the
    problem and its tests only. Never the solution."""
    await hit("code_review", str(user.id))
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    q = next((q for q in s.questions if q["id"] == body.question_id), None)
    if q is None or q.get("kind") != "coding":
        raise HTTPException(404, "No such coding question")
    from app.services.coding_bank import BY_ID
    from app.services.interview_panel import clarify

    p = BY_ID.get(q["problem"]["id"])
    problem = {**q["problem"], "tests": [{"args": t["args"], "expected": t["expected"], "visible": t.get("visible", False)} for t in (p.tests if p else [])]}
    return {"answer": await clarify(problem, body.question, user.id)}


@router.get("/interviews/{session_id}/report")
async def full_report(session_id: str, user: UserDep, session: SessionDep) -> dict:
    """Every round against the field's norms at your level: strengths, gaps, improvements, coding verdicts, and an
    overall practice signal. The AI-written summary is generated once and kept."""
    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    return await _report(s, user, session)


@router.get("/interviews/{session_id}/report/download")
async def download_report(session_id: str, user: UserDep, session: SessionDep, format: Literal["pdf", "docx"] = "pdf") -> Response:
    """The whole interview in one document (PDF or Word): the interviewer's evaluation (1-5 matrix, strengths, concerns,
    recommendation), every question with your answer, score and how to answer it (with a sample answer), and a
    self-assessment with the follow-up checklist. Each part starts on a new page. The answer guides are written once
    per finished interview and kept."""
    from app.services import interview_report_doc
    from app.services.interview_answers import build_guides

    s = await session.get(InterviewSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such session")
    if not s.scores:
        raise HTTPException(409, "Answer at least one question first: the report covers what you answered.")
    rep = await _report(s, user, session)
    guides = (s.meta or {}).get("answer_guides")
    if not guides or set(guides) != {q["id"] for q in s.questions}:
        await hit("interview_report", str(user.id))
        profile = await _profile(session, user.id)
        guides = await build_guides(s, ResumeData.model_validate((profile.resume if profile else None) or {}), user.id)
        if s.completed_at:
            s.meta = {**(s.meta or {}), "answer_guides": guides}
            await session.commit()
    profile = await _profile(session, user.id)
    candidate = (user.name or "").strip() or (ResumeData.model_validate((profile.resume if profile else None) or {}).name or "").strip()
    data = interview_report_doc.compose(s, rep, guides, candidate)
    if format == "pdf":
        content, mime = interview_report_doc.render_pdf(data), "application/pdf"
    else:
        content, mime = interview_report_doc.render_docx(data), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{interview_report_doc.filename(data, format)}"'})


@router.get("/interviews/trends/{industry}")
async def trends(industry: str, user: UserDep) -> dict:
    """The skills rising in this field's postings (or the curated snapshot until there are enough postings)."""
    if industry not in INDUSTRIES:
        raise HTTPException(404, "Unknown field")
    out = await trending_skills(industry)
    out["questions"] = await trend_questions(industry, 6)
    return out


@router.post("/admin/trends/refresh")
async def refresh_trends(user: AdminDep) -> dict:
    """Admin: re-measure trends from postings and refresh the question bank now (it also runs weekly)."""
    return await refresh_question_trends()

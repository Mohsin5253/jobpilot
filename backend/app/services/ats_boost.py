"""Boost a resume toward a target ATS score (default 90) for its field, without inventing anything.

What can be done automatically is done: structure, a summary from the resume's own facts, strong action verbs,
skills ordered by what the field searches for, keywords the student confirms, each role's stack counted where
recruiters search. What can't be done honestly without the student is asked for: the real figure behind each bullet
that has no measurable result. Given those figures, bullets are rewritten in Google's XYZ form ("Accomplished X, as
measured by Y, by doing Z") using only the bullet's facts and the student's figure (checked: no new number, no new
tool). The response says how far the score can go once the remaining figures are added.
"""

import re

from pydantic import BaseModel, Field

from app.agents.guard import check_claim
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.schemas import ResumeData
from app.services import ats
from app.services.resume_improve import improve
from app.skills import extract_skills

_NUM = re.compile(r"\d+(?:[.,]\d+)*")

XYZ_SYSTEM = """You rewrite resume bullets in Google's XYZ form: accomplished X, as measured by Y, by doing Z. Write it the
way strong resumes do, not with the literal words "as measured by". Examples:
- "Reduced operational cost by 35% by migrating Hive and Presto jobs from Qubole to AWS EMR."
- "Built a desktop dictionary app used by 150 classmates, with Trie-based search and edit-distance spelling correction."
Rules (strict):
- Use ONLY the facts in the bullet and the candidate's own figure. Never add a number, tool, team size or outcome.
- One line, under 30 words, starting with a strong past-tense action verb. No first person, no brackets.
- Put the figure where it shows the result (the Y). Keep every technology the bullet names.
Return the bullets in the same order and the same count."""


class XYZ(BaseModel):
    bullets: list[str] = Field(description="The rewritten bullets, same order and count")


def _question(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(model|accuracy|predict|classif|train)", low):
        return "What accuracy, F1 or error did it reach (and on how much data)?"
    if re.search(r"\b(api|backend|server|query|database|latency|performance|optimi[sz])", low):
        return "How much faster or bigger: latency, requests/day, % time saved?"
    if re.search(r"\b(app|website|platform|tool|portal|dashboard)", low):
        return "How many people used it, or what did it save them?"
    if re.search(r"\b(sales|revenue|campaign|marketing|leads|growth)", low):
        return "What changed in numbers: ₹, %, leads, CTR, signups?"
    if re.search(r"\b(cost|migrat|automat|pipeline|workflow|infrastructure)", low):
        return "What did it save or speed up: ₹, %, hours, jobs/day?"
    if re.search(r"\b(led|managed|organi[sz]ed|team|event|club)", low):
        return "How many people, events or how much budget?"
    return "What was the measurable result: users, %, time, money, rank?"


def _ok_figure(fig: str) -> bool:
    return bool(fig and len(fig) <= 120 and _NUM.search(fig))


def _rule_xyz(bullet: str, figure: str) -> str:
    b = bullet.strip().rstrip(".")
    f = figure.strip().rstrip(".")
    return f"{b}, {f}." if re.match(r"^(cutting|reducing|raising|increasing|improving|saving|serving|reaching|helping|resulting)", f, re.I) else f"{b} ({f})."


async def apply_figures(resume: ResumeData, figures: dict[str, str], user_id) -> tuple[ResumeData, list[dict]]:
    """Bullets rewritten with the student's own figures (XYZ form). Each rewrite may use only the bullet's facts and
    the figure: a rewrite with any other number or tool falls back to the bullet plus the figure, word for word."""
    new = resume.model_copy(deep=True)
    index = dict(new.bullet_index())
    todo = [(sid, index[sid], fig.strip()) for sid, fig in figures.items() if sid in index and _ok_figure(fig.strip())][:15]
    if not todo:
        return new, []
    rewrites: dict[str, str] = {}
    try:
        out = await get_llm().structured(
            agent="tailor",
            tier="smart",
            schema=XYZ,
            ctx=CallContext(user_id=user_id),
            max_tokens=1500,
            system=XYZ_SYSTEM,
            prompt="\n".join(f"{i + 1}. Bullet: {b}\n   Candidate's figure: {f}" for i, (_, b, f) in enumerate(todo)),
        )
        if len(out.bullets) == len(todo):
            for (sid, b, f), rw in zip(todo, out.bullets):
                rw = re.sub(r"^\s*\d+[.)]\s*", "", rw).strip()
                allowed_nums = set(_NUM.findall(f"{b} {f}"))
                new_nums = set(_NUM.findall(rw)) - allowed_nums
                ok = rw and "[" not in rw and not new_nums and check_claim(rw, [sid], {sid: f"{b} {f}"}, set(extract_skills(b)) | set(resume.skills)).ok
                if ok:
                    rewrites[sid] = rw
    except (LLMUnavailable, LLMOutputError):
        pass
    changes = []
    for sid, b, f in todo:
        rw = rewrites.get(sid) or _rule_xyz(b, f)
        m = re.match(r"(exp|proj)(\d+)\.b(\d+)$", sid)
        if not m:
            continue
        items = new.experience if m.group(1) == "exp" else new.projects
        items[int(m.group(2))].bullets[int(m.group(3))] = rw
        changes.append({"section": "Experience" if m.group(1) == "exp" else "Projects", "before": b, "after": rw, "why": "Your real figure, in Google's XYZ form: what you achieved, how it was measured, how you did it."})
    return new, changes


def needs_figures(resume: ResumeData, limit: int = 12) -> list[dict]:
    """Bullets with no measurable result, each with the question that gets the right figure."""
    out = []
    for sid, text in resume.bullet_index():
        if not sid.startswith(("exp", "proj")) or not text.strip():
            continue
        if "no measurable result" in ats.bullet_issues(text):
            out.append({"id": sid, "text": text, "question": _question(text), "example": "e.g. 200 users, 35% faster, ₹40k saved, top 5 of 300"})
    return out[:limit]


def _potential(resume: ResumeData, industry: str, title: str, desc: str) -> int:
    """The score once every bullet has its real figure (simulated with a placeholder number)."""
    sim = resume.model_copy(deep=True)
    for items in (sim.experience, sim.projects):
        for it in items:
            it.bullets = [b if _NUM.search(b) else f"{b.rstrip('.')} (1)." for b in it.bullets]
    return ats.score(ats.view_from_resume(sim), industry, title, desc)["score"]


async def boost(
    resume: ResumeData,
    industry_key: str | None,
    job_title: str,
    job_description: str,
    confirmed: list[str],
    figures: dict[str, str],
    target: int,
    user_id,
    raw_text: str | None = None,
    filename: str | None = None,
) -> dict:
    before = ats.score(ats.view_from_resume(resume, raw_text, filename), industry_key, job_title, job_description)
    industry = before["industry"]
    # 1) The student's own figures first, so the next step sees those bullets as already strong.
    with_figures, fig_changes = await apply_figures(resume, figures, user_id)
    # 2) Everything automatic: verbs, summary, confirmed keywords, skill order.
    out = await improve(with_figures, industry, job_title, job_description, confirmed, user_id)
    new = ResumeData.model_validate(out["resume"])
    after = out["after_report"]
    asks = needs_figures(new)
    potential = _potential(new, industry, job_title, job_description) if asks else after["score"]
    remaining = [i for i in after.get("improvements", []) if i.get("area") != "impact"][:5]
    reached = after["score"] >= target
    if reached:
        note = f"Target reached: {after['score']} for {after.get('industry_name', industry)}."
    elif asks and potential >= target:
        note = f"Add the {len(asks)} figure{'s' if len(asks) != 1 else ''} below to reach about {potential}. Only use numbers you can explain in an interview."
    elif asks:
        note = f"With the figures below you'd reach about {potential}; the steps listed after them close the rest of the gap to {target}."
    else:
        note = f"{after['score']} is as far as automatic fixes go; the steps below close the gap to {target}."
    return {
        **out,
        "changes": [*fig_changes, *out["changes"]],
        "before": before["score"],
        "target": target,
        "reached": reached,
        "potential": max(potential, after["score"]),
        "needs_figures": asks,
        "remaining": remaining,
        "industry": industry,
        "industry_name": after.get("industry_name", industry),
        "note": note,
    }

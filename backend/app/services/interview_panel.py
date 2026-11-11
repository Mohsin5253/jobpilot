"""The interview panel: how the mock interviewer behaves like a large-tech interviewer, and how the finished interview
is evaluated by a small ensemble instead of one grader.

During the interview
- Follow-ups: after an answer, the interviewer pushes back once, the way trained interviewers do ("Your budget is cut
  by 50%: what changes?", "What exactly was your part?"). The answer to it is graded with the original.
- Coding stages: clarify → approach & complexity → implement → test & optimise. Clarifying questions are answered from
  the problem and its tests (never the solution); starting to code without clarifying, or without stating complexity,
  costs process points, as it would with a real interviewer.

After the interview: three evaluators run in parallel over the transcript, each with its own rubric
- the Scribe extracts each answer's structure (STAR / CIRCLES / case elements present or missing),
- the Technical Critic judges correctness, complexity reasoning and edge cases (coding and technical answers),
- the Behavioural Coach looks for leadership and Googleyness signals (ownership, humility, ambiguity, collaboration),
and the result is a scorecard on four attributes (general cognitive ability, role-related knowledge, leadership,
Googleyness; 1-4 each) with a five-tier verdict: Strong No Hire, No Hire, Leaning Hire, Hire, Strong Hire.
Each evaluator falls back to rules when the AI is unavailable, so the scorecard always exists.
"""

import asyncio
import re

from pydantic import BaseModel, Field

from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.services.interview_rubrics import as_prompt, retrieve

VERDICTS = ("Strong No Hire", "No Hire", "Leaning Hire", "Hire", "Strong Hire")
ATTRIBUTES = {
    "gca": "General cognitive ability",
    "rrk": "Role-related knowledge",
    "leadership": "Leadership & ownership",
    "googleyness": "Googleyness (collaboration, humility, ambiguity)",
}
FOLLOW_UP_KINDS = {"behavioural", "situational", "skill", "project", "proof", "case", "technical", "roleplay", "portfolio", "screening", "trend"}

# ---------- follow-ups ----------

FOLLOW_UPS = {
    "behavioural": ["What exactly was your part, as opposed to the team's?", "If you did it again tomorrow, what would you do differently, and why?"],
    "situational": ["Suppose your manager disagrees with that plan. What do you do?", "What if you had half the time? What would you cut?"],
    "case": ["Your budget is suddenly cut by 50%. How does your recommendation change?", "Your main data source fails. Which metric would you watch instead, and why?"],
    "product": ["How would you know in two weeks whether this worked? Name the metric.", "A competitor ships the same feature first. What do you change?"],
    "technical": ["How would that hold up at ten times the load?", "What's the main trade-off in that approach, and when would you choose the alternative?"],
    "skill": ["What was the hardest bug or problem you hit with it, and how did you solve it?", "What would you do differently with it now?"],
    "project": ["Why did you choose that design over the obvious alternative?", "What broke first when real users touched it?"],
    "roleplay": ["The customer says it's too expensive. What do you say next?", "They ask for a feature you don't have. How do you respond?"],
    "screening": ["Why this role over the others you're applying to?", "What's one thing on your resume you'd love to be asked about, and why?"],
}


class FollowUp(BaseModel):
    question: str = Field(description="One short follow-up question, under 30 words")


async def follow_up(q: dict, answer: str, user_id) -> str:
    """One probing follow-up to this answer, like a trained interviewer: push on an assumption, add a constraint, or
    ask for the candidate's own part. Falls back to the kind's standard probes."""
    kind = q.get("kind") or "behavioural"
    pool = FOLLOW_UPS.get(kind) or FOLLOW_UPS["behavioural"]
    fallback = pool[len(answer) % len(pool)]
    try:
        res = await get_llm().structured(
            agent="interviewer",
            tier="fast",
            schema=FollowUp,
            ctx=CallContext(user_id=user_id),
            max_tokens=150,
            system=(
                "You are a trained interviewer at a large tech company. Ask ONE follow-up to the candidate's answer that "
                "tests depth: challenge an assumption, add a realistic constraint (budget cut, failed data source, 10x scale, "
                "a disagreeing stakeholder) or ask what they personally did. Refer to something they actually said. Under 30 words."
            ),
            prompt=f"Question ({kind}): {q['q']}\nCandidate's answer: {answer[:2000]}",
        )
        text = res.question.strip()
        return text if 5 <= len(text.split()) <= 40 else fallback
    except (LLMUnavailable, LLMOutputError):
        return fallback


# ---------- coding: clarifying questions and process ----------


class Clarification(BaseModel):
    answer: str = Field(description="A short, direct answer (under 40 words). Never give the algorithm or code.")


def _rule_clarify(problem: dict, question: str) -> str:
    low = question.lower()
    tests = problem.get("tests") or []
    args = [t.get("args") for t in tests]
    flat = repr(args)
    if re.search(r"empty|null|none|zero[- ]length", low):
        has_empty = any(a and any(x in ([], "", {}) for x in a) for a in args)
        return "Yes, handle empty input: it's one of the tests." if has_empty else "You can assume the input isn't empty, but handling it is good practice."
    if re.search(r"duplicate|repeat", low):
        return "Yes, duplicates can appear." if re.search(r"(\d+), \1\b", flat) else "Don't assume values are unique."
    if re.search(r"negative", low):
        return "Yes, negative numbers can appear." if "-" in flat else "Assume they can, unless the statement says otherwise."
    if re.search(r"size|large|big|constraint|how many|limit|range|n\b", low):
        return "Assume up to about 10^5 elements, so aim for better than O(n²)."
    if re.search(r"sorted|order", low):
        return "Don't assume the input is sorted unless the statement says so."
    if re.search(r"return|output|format", low):
        return "Return exactly what the statement and examples show."
    return "Good question. Assume valid input as described; state any other assumption out loud and handle edge cases."


async def clarify(problem: dict, question: str, user_id) -> str:
    """The interviewer's answer to a clarifying question, from the problem and its tests only."""
    try:
        visible = [t for t in problem.get("tests", []) if t.get("visible")][:3]
        res = await get_llm().structured(
            agent="interviewer",
            tier="fast",
            schema=Clarification,
            ctx=CallContext(user_id=user_id),
            max_tokens=150,
            system=(
                "You are the interviewer in a coding interview. Answer the candidate's clarifying question briefly, "
                "using only the problem statement and examples. Confirm constraints and edge cases; if unspecified, give "
                "a sensible assumption (e.g. up to 10^5 elements). Never reveal the algorithm, data structure or code."
            ),
            prompt=f"Problem: {problem.get('title')}: {problem.get('statement')}\nExamples: {visible}\nCandidate asks: {question[:400]}",
        )
        text = res.answer.strip()
        return text or _rule_clarify(problem, question)
    except (LLMUnavailable, LLMOutputError):
        return _rule_clarify(problem, question)


def _norm_big_o(s: str) -> str:
    s = (s or "").lower().replace(" ", "").replace("²", "^2").replace("**", "^")
    s = s.replace("logn", "log(n)").replace("nlog(n)", "n*log(n)")
    m = re.search(r"o\(([^)]*\)?)\)?", s)
    return m.group(1) if m else s


def process_scores(process: dict, hint_complexity: str) -> dict:
    """1-5 for each stage a coding interviewer watches: clarification, design (complexity stated and right), testing."""
    asked = [c for c in (process.get("clarifications") or []) if (c.get("q") or "").strip()]
    clarification = 1 if not asked else 3 if len(asked) == 1 else 4 if len(asked) == 2 else 5
    t, sp = (process.get("time_complexity") or "").strip(), (process.get("space_complexity") or "").strip()
    if not t:
        design = 1
    else:
        want = _norm_big_o(hint_complexity.split(",")[0] if hint_complexity else "")
        design = 5 if want and _norm_big_o(t) == want else 3
        design = min(5, design + (1 if sp else 0)) if design < 5 else 5
    notes = (process.get("test_notes") or "").strip().lower()
    testing = 1 if not notes else 4 if re.search(r"edge|empty|duplicate|negative|large|overflow|optimi[sz]|faster|memory|bug", notes) else 2
    if notes and len(notes.split()) >= 25:
        testing = min(5, testing + 1)
    feedback = []
    if clarification <= 2:
        feedback.append("Ask 1-2 clarifying questions (input size, empty input, duplicates) before designing; interviewers note when you don't.")
    if design <= 3:
        feedback.append(f"State time and space complexity before coding{f' (target: {hint_complexity})' if hint_complexity else ''}.")
    if testing <= 2:
        feedback.append("After coding, walk through an edge case out loud and say what you'd optimise next.")
    return {"clarification": clarification, "design": design, "testing": testing, "process_feedback": feedback}


# ---------- after the interview: the evaluator ensemble ----------


class ScribeItem(BaseModel):
    n: int
    framework: str = Field(description="STAR, CIRCLES, case structure, technical explanation, or none")
    present: list[str] = Field(default_factory=list, description="Elements present (e.g. Situation, Action, Result)")
    missing: list[str] = Field(default_factory=list, description="Elements missing")


class Scribe(BaseModel):
    answers: list[ScribeItem]


class Signal(BaseModel):
    attribute: str = Field(description="gca, rrk, leadership or googleyness")
    score: int = Field(ge=1, le=4, description="1 = strong concern, 2 = concern, 3 = meets the bar, 4 = strong")
    evidence: str = Field(description="A short quote or paraphrase from the candidate's answers")
    comment: str = Field(description="One sentence: why this score")


class Critique(BaseModel):
    signals: list[Signal]
    notes: list[str] = Field(default_factory=list, description="Up to 4 specific observations")


def _transcript(s, kinds: set[str] | None = None, limit: int = 600) -> str:
    rows = []
    for n, q in enumerate(s.questions, 1):
        if kinds and (q.get("kind") not in kinds):
            continue
        a = (s.answers or {}).get(q["id"], "")
        sc = (s.scores or {}).get(q["id"]) or {}
        rows.append(f"Q{n} [{q.get('round_name', '')} · {q.get('kind')}]: {q['q'][:300]}\nA{n}: {a[:limit] or '(not answered)'}\nScore: {sc.get('score', '-')}/5")
    return "\n\n".join(rows)


async def _scribe(s, user_id) -> list[dict] | None:
    verbal = [q for q in s.questions if q.get("kind") != "coding"]
    if not verbal:
        return []
    try:
        res = await get_llm().structured(
            agent="interviewer", tier="fast", schema=Scribe, ctx=CallContext(user_id=user_id), max_tokens=1500,
            system="You are the panel's scribe. For each answer, name the framework a strong answer would use (STAR for behavioural, CIRCLES for product, case structure, technical explanation) and list which of its elements the candidate covered and which are missing. Be literal; no judgement.",
            prompt=_transcript(s, {q.get("kind") for q in verbal}),
        )
        return [a.model_dump() for a in res.answers]
    except (LLMUnavailable, LLMOutputError):
        return None


async def _critic(s, user_id, system: str, kinds: set[str], rubric_kinds: list[str], industry: str) -> Critique | None:
    if not any(q.get("kind") in kinds for q in s.questions):
        return None
    rubrics = []
    for k in rubric_kinds:
        rubrics += [r for r in retrieve(k, industry, 3) if r not in rubrics]
    try:
        return await get_llm().structured(
            agent="interviewer", tier="smart", schema=Critique, ctx=CallContext(user_id=user_id), max_tokens=1200,
            system=system + "\nGrade against these rubrics:\n" + as_prompt(rubrics) + "\nUse the 1-4 scale: 1 strong concern, 2 concern, 3 meets the bar for this level, 4 strong. Quote evidence.",
            prompt=_transcript(s, kinds),
        )
    except (LLMUnavailable, LLMOutputError):
        return None


def _rule_signals(s) -> dict[str, dict]:
    """Attribute scores from the per-answer rubric scores, when the AI evaluators aren't available."""
    def avg(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return sum(xs) / len(xs) if xs else None

    by: dict[str, list[float]] = {"gca": [], "rrk": [], "leadership": [], "googleyness": []}
    for q in s.questions:
        sc = (s.scores or {}).get(q["id"])
        if not sc or sc.get("integrity_flags"):
            continue
        k = q.get("kind")
        if k == "coding":
            by["gca"] += [sc.get("efficiency"), sc.get("design")]
            by["rrk"] += [sc.get("correctness"), sc.get("quality")]
        elif k in ("case", "situational"):
            by["gca"].append(sc.get("score"))
        elif k in ("technical", "skill", "trend", "portfolio"):
            by["rrk"].append(sc.get("score"))
        elif k in ("project", "proof"):
            by["rrk"].append(sc.get("score"))
            by["leadership"].append(sc.get("specificity"))
        else:
            by["leadership"].append(sc.get("specificity"))
            by["googleyness"].append(sc.get("score"))
    out = {}
    for key, xs in by.items():
        a = avg(xs)
        if a is None:
            continue
        score = 4 if a >= 4.3 else 3 if a >= 3.4 else 2 if a >= 2.3 else 1
        out[key] = {"key": key, "label": ATTRIBUTES[key], "score": score, "evidence": "", "comment": f"From the rubric scores of the {ATTRIBUTES[key].lower()} questions (average {a:.1f}/5)."}
    return out


def verdict(attrs: list[dict], terminated: bool = False) -> str:
    """Five tiers from the attribute scores (1-4): any strong concern blocks a hire; all strong is a strong hire."""
    if terminated:
        return "No Hire"
    scores = [a["score"] for a in attrs if a.get("score")]
    if not scores:
        return "No Hire"
    avg = sum(scores) / len(scores)
    if min(scores) == 1 and avg < 2.5:
        return "Strong No Hire"
    if min(scores) == 1 or avg < 2.5:
        return "No Hire"
    if avg >= 3.6 and min(scores) >= 3:
        return "Strong Hire"
    if avg >= 3.0 and min(scores) >= 3:
        return "Hire"
    return "Leaning Hire"


async def evaluate(s, user_id) -> dict:
    """The panel's scorecard for a finished interview. Three evaluators run at once; each falls back to rules."""
    industry = (s.meta or {}).get("industry", "software")
    technical = {"coding", "technical", "skill", "trend", "case", "portfolio"}
    behavioural = {"behavioural", "situational", "screening", "project", "proof", "roleplay"}
    scribe, tech, coach = await asyncio.gather(
        _scribe(s, user_id),
        _critic(s, user_id, "You are the panel's technical critic. Judge only problem-solving and role knowledge: correctness, depth, complexity reasoning, edge cases, trade-offs. Score the attributes gca and rrk.", technical, ["coding", "technical", "case"], industry),
        _critic(s, user_id, "You are the panel's behavioural coach. Judge only leadership and Googleyness signals: ownership, bias to action, intellectual humility, collaboration, comfort with ambiguity, handling pushback. Score the attributes leadership and googleyness.", behavioural, ["behavioural", "situational"], industry),
    )
    attrs = _rule_signals(s)
    ai = False
    for crit, allowed in ((tech, {"gca", "rrk"}), (coach, {"leadership", "googleyness"})):
        if not crit:
            continue
        for sig in crit.signals:
            key = sig.attribute.strip().lower()
            if key in allowed:
                rule = attrs.get(key)
                # The AI's judgement can't drift more than one step from what the rubric scores show.
                score = sig.score if not rule else max(rule["score"] - 1, min(rule["score"] + 1, sig.score))
                attrs[key] = {"key": key, "label": ATTRIBUTES[key], "score": score, "evidence": sig.evidence.strip()[:240], "comment": sig.comment.strip()[:240]}
                ai = True
    ordered = [attrs[k] for k in ATTRIBUTES if k in attrs]
    return {
        "attributes": ordered,
        "verdict": verdict(ordered, (s.status or "") == "terminated"),
        "scribe": scribe or [],
        "technical_notes": (tech.notes if tech else [])[:4],
        "behavioural_notes": (coach.notes if coach else [])[:4],
        "ai": ai,
    }

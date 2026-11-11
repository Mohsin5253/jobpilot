"""The end-of-interview report: every round graded against the field's norms at the candidate's level, with strengths,
gaps and improvements, the coding verdicts, and an overall signal in the words hiring panels use.

Signals (practice only, never shared): Strong hire / Hire / Lean no / No hire, from the average rubric score against
the level's bar (interns 3.2/5, freshers 3.6/5) and how many rounds fell below it. An interview ended for integrity
reasons is reported as such. An AI-written summary is added when available; everything else is rule-based, so the
report is the same every time it's opened.
"""

from collections import Counter

from pydantic import BaseModel, Field

from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.services.interview_rounds import BAR, norm_for

COMPONENTS = {
    "verbal": {"relevance": "Relevance to what was asked", "specificity": "Specific examples and numbers", "structure": "Structure (situation → action → result)"},
    "coding": {"correctness": "Correctness", "efficiency": "Efficiency vs the expected complexity", "quality": "Code quality", "communication": "Explaining the approach"},
}
GAP_TEXT = {
    "relevance": "Answers drifted from what was asked. Restate the question in one line, then answer that.",
    "specificity": "Answers stayed general. Name what you personally did and add one number (users, %, time, rank).",
    "structure": "Answers lacked a clear arc. Use situation → what you did → result.",
    "correctness": "Solutions didn't pass all tests. Dry-run examples and edge cases (empty input, duplicates) before submitting.",
    "efficiency": "Solutions were slower than expected. Start from brute force, then look for a hash map, sorting or two pointers.",
    "quality": "Code was hard to read. Use descriptive names and small helper functions.",
    "communication": "The approach wasn't explained. Say the idea, complexity and edge cases before you code.",
}
# Where to practise, per kind of round (and per field where it differs).
RESOURCES = {
    "coding": "Timebox two problems a day (one easy, one medium) on arrays, hash maps, strings and two pointers; say the complexity out loud before coding.",
    "technical": "Make a one-page sheet per core topic with your own example for each concept, and explain it aloud in two minutes.",
    "case": "Practise one case a day with a framework (profitability, market entry, root cause) and finish with a one-line recommendation.",
    "roleplay": "Record a 60-second pitch and an objection response; listen back for questions you skipped before pitching.",
    "portfolio": "Rewrite one case study as problem → research → options → decision → outcome, with one user quote and one metric.",
    "project": "For each project, prepare: the problem, your part, one hard decision with its trade-off, and a measurable result.",
    "screening": "Script and time a 60-second introduction tailored to this role; research two facts about the company.",
    "behavioural": "Prepare five STAR stories (conflict, failure, leadership, learning fast, deadline) with your own actions and outcomes.",
}
FIELD_RESOURCES = {
    ("data_science", "coding"): "Implement metrics, cosine similarity, softmax and a small retrieval step in plain Python; handle division by zero and empty input.",
    ("data_science", "technical"): "Review bias-variance, precision/recall trade-offs and leakage; build a tiny RAG demo and write how you'd evaluate it.",
    ("data_analytics", "coding"): "Solve SQL-style problems (GROUP BY, window functions, dedupe) in both SQL and Python.",
    ("marketing", "case"): "For three brands you like, write a 1-month plan with budget split, channels and target CTR/CAC/ROAS.",
    ("finance", "technical"): "Practise linking the three statements and a 5-step DCF aloud; revise GST input tax credit and TDS basics.",
    ("consulting", "case"): "Do one guesstimate and one profitability case daily; practise mental maths with rounded numbers.",
    ("sales", "roleplay"): "Practise discovery questions (BANT) before any pitch; prepare answers to the five most common objections.",
}


def _signal(avg: float | None, below: int, bar: float, terminated: bool) -> str:
    if terminated:
        return "Ended early"
    if avg is None:
        return "Not enough answers"
    if avg >= bar + 0.8 and below == 0:
        return "Strong hire"
    if avg >= bar and below <= 1:
        return "Hire"
    if avg >= bar - 0.5:
        return "Lean no"
    return "No hire"


def build(s) -> dict:
    meta = s.meta or {}
    industry, level = meta.get("industry", "software"), meta.get("level", "intern")
    bar = BAR.get(level, 3.2)
    rounds = []
    tips: Counter = Counter()
    for r in meta.get("rounds", []):
        qs = [q for q in s.questions if q.get("round") == r["index"]]
        scored = [(q, s.scores[q["id"]]) for q in qs if q["id"] in s.scores]
        kind = "coding" if r["kind"] == "coding" else "verbal"
        comps = COMPONENTS[kind]
        comp_avg = {c: round(sum(sc.get(c, 0) for _, sc in scored) / len(scored), 1) for c in comps} if scored else {}
        avg = round(sum(sc["score"] for _, sc in scored) / len(scored), 1) if scored else None
        status = "Not attempted" if avg is None else "Above bar" if avg >= bar + 0.5 else "Meets bar" if avg >= bar else "Below bar"
        strengths = [f"{comps[c]} ({v}/5)" for c, v in sorted(comp_avg.items(), key=lambda kv: -kv[1]) if v >= 4][:3]
        gaps = [GAP_TEXT[c] for c, v in sorted(comp_avg.items(), key=lambda kv: kv[1]) if v < 3][:3]
        unanswered = len(qs) - len(scored)
        if unanswered:
            gaps.append(f"{unanswered} question(s) in this round weren't answered.")
        flagged = [q for q, sc in scored if sc.get("integrity_flags")]
        if flagged:
            gaps.append(f"{len(flagged)} answer(s) didn't count (not typed or spoken in the interview).")
        for _, sc in scored:
            for f in (sc.get("improvements") or sc.get("feedback") or [])[:2]:
                if not f.startswith("Not counted"):
                    tips[f] += 1
        improvements = [FIELD_RESOURCES.get((industry, r["kind"])) or RESOURCES.get(r["kind"], RESOURCES["technical"])]
        improvements += [t for t, _ in Counter(f for _, sc in scored for f in (sc.get("improvements") or sc.get("feedback") or [])[:2] if not f.startswith("Not counted")).most_common(2)]
        row = {
            "index": r["index"],
            "name": r["name"],
            "kind": r["kind"],
            "score": avg,
            "bar": bar,
            "status": status,
            "norm": r.get("norm") or norm_for(industry, r["kind"]),
            "components": [{"key": c, "label": comps[c], "score": comp_avg.get(c)} for c in comps] if scored else [],
            "strengths": strengths,
            "gaps": gaps,
            "improvements": list(dict.fromkeys(improvements))[:4],
            "answered": len(scored),
            "total": len(qs),
        }
        if r["kind"] == "coding":
            row["coding"] = [
                {
                    "title": (q.get("problem") or {}).get("title", q["q"][:60]),
                    "difficulty": (q.get("problem") or {}).get("difficulty"),
                    "verdict": sc.get("verdict", "not submitted"),
                    "tests": sc.get("tests_label", ""),
                    "complexity": f"{sc.get('time_complexity', '?')} time, {sc.get('space_complexity', '?')} space",
                    "optimal": sc.get("optimal"),
                    "summary": sc.get("summary", ""),
                    "language": sc.get("language"),
                }
                if sc
                else {"title": (q.get("problem") or {}).get("title", q["q"][:60]), "difficulty": (q.get("problem") or {}).get("difficulty"), "verdict": "not submitted"}
                for q in qs
                for sc in [s.scores.get(q["id"])]
            ]
        rounds.append(row)
    scores = [v["score"] for v in s.scores.values()]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    below = sum(1 for r in rounds if r["status"] in ("Below bar", "Not attempted"))
    terminated = (s.status or "") == "terminated"
    gaps_all = [g for r in rounds for g in r["gaps"]]
    focus = [r for r in sorted(rounds, key=lambda r: (r["score"] if r["score"] is not None else 0)) if r["status"] in ("Below bar", "Not attempted")][:3]
    return {
        "industry": industry,
        "industry_name": meta.get("industry_name", industry),
        "level": level,
        "minutes": meta.get("minutes"),
        "bar": bar,
        "score": avg,
        "signal": _signal(avg, below, bar, terminated),
        "rounds": rounds,
        "focus": [{"round": r["name"], "do": r["improvements"][0]} for r in focus],
        "gap_count": len(gaps_all),
        "summary": meta.get("report_ai", {}).get("summary"),
        "next_week": meta.get("report_ai", {}).get("next_week", []),
    }


class Narrative(BaseModel):
    summary: str = Field(description="4-5 sentences, second person, honest and encouraging")
    next_week: list[str] = Field(max_length=3, description="Three concrete practice steps for the next 7 days")


async def narrative(report: dict, user_id) -> dict | None:
    """An interviewer-style summary of the report. None when the AI isn't available."""
    try:
        lines = [f"{r['name']}: {r['score']}/5 ({r['status']}); gaps: {'; '.join(r['gaps'][:2]) or 'none'}" for r in report["rounds"]]
        res = await get_llm().structured(
            agent="interviewer",
            tier="fast",
            schema=Narrative,
            ctx=CallContext(user_id=user_id),
            max_tokens=500,
            system="You are the interview panel lead giving a candidate practice feedback after a mock interview for an Indian internship or fresher role. Be specific to the rounds; no generic advice.",
            prompt=f"Field: {report['industry_name']} · Level: {report['level']} · Bar: {report['bar']}/5 · Overall: {report['score']}/5 · Signal: {report['signal']}\n" + "\n".join(lines),
        )
        return res.model_dump()
    except (LLMUnavailable, LLMOutputError):
        return None

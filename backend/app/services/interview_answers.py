"""How to answer each question of a finished mock interview: what the interviewer was testing, the steps of a strong
answer, the points to mention, what to avoid, and a sample answer.

Sample answers use the candidate's own resume (projects, skills, roles). Where a strong answer needs a fact we don't
have, the sample leaves a [bracketed placeholder] for the candidate to fill in, so no achievement is ever invented.
Coding questions show the verified reference solution (it passes every test of that problem).
Written once per interview (AI, in batches) and stored on the session; without the AI, guides come from rules.
"""

import re

from pydantic import BaseModel, Field

from app.safety import untrusted
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.schemas import ResumeData
from app.services.coding_bank import BY_ID
from app.services.coding_solutions import sample_solution
from app.skills import extract_skills

# Steps of a strong answer, by kind of question.
APPROACH = {
    "screening": ["Open with who you are in one line: degree, college, year.", "Pick the two experiences most relevant to this role and say what you did in each.", "Close with why this role and company, in one sentence."],
    "behavioural": ["Situation: one or two lines of context (when, where, what was at stake).", "Task: what you personally were responsible for.", "Action: the steps you took, using “I”, not “we”.", "Result: the outcome with a number, and what you learned."],
    "situational": ["Restate the situation to show you understood it.", "Say what you would do first, then next, and why.", "Mention who you'd involve and how you'd check it worked.", "Back it with a time you did something similar."],
    "skill": ["Name the project or task where you used the skill.", "Explain what you built with it and one hard part you solved.", "Give the result: a number, a user, a grade, a shipped feature.", "Say what you'd do better now."],
    "technical": ["Define the concept in one plain sentence.", "Give a small concrete example (from your project if possible).", "Explain the trade-off or when you would not use it.", "Connect it to the role's work."],
    "case": ["Clarify the goal and any constraints before solving.", "Lay out a structure (e.g. revenue vs cost, market → customers → competitors).", "Work through the most important branch with rough numbers, saying assumptions out loud.", "End with a clear recommendation and one risk to check."],
    "roleplay": ["Ask two or three discovery questions before pitching.", "Link one benefit to each need you heard.", "Handle the objection: acknowledge, ask why, answer with proof.", "Close with a concrete next step."],
    "portfolio": ["The problem and who it was for.", "Your research and what it showed (one quote or metric).", "Options you considered and why you chose one.", "The outcome and what you'd change."],
    "project": ["The problem and why it mattered.", "Your part and the key design choice, with its trade-off.", "One hard bug or decision and how you resolved it.", "The result, and what you'd do differently."],
    "proof": ["The problem and why it mattered.", "Your part and the key design choice, with its trade-off.", "One hard bug or decision and how you resolved it.", "The result, and what you'd do differently."],
    "coding": ["Restate the problem and confirm input/output with one example.", "Say the brute-force idea and its complexity.", "Improve it (hash map, sorting, two pointers, stack, BFS/DP as fits) and state the new complexity.", "Code it cleanly, then dry-run an example and the edge cases (empty input, duplicates, limits)."],
}
AVOID = {
    "screening": ["Reading out your whole resume.", "Generic lines like “I am hardworking and passionate”."],
    "behavioural": ["Saying “we” throughout so your own part is unclear.", "Ending without a result."],
    "situational": ["Answering only in theory with no example.", "Skipping how you'd check it worked."],
    "skill": ["Listing the tool without saying what you built with it."],
    "technical": ["Textbook definitions with no example.", "Bluffing; say what you know and how you'd find out the rest."],
    "case": ["Jumping to an answer without a structure.", "Doing maths silently; say your assumptions."],
    "roleplay": ["Pitching before asking what the customer needs."],
    "portfolio": ["Showing only final screens without the reasoning."],
    "project": ["Describing the tech stack instead of your decisions."],
    "proof": ["Describing the tech stack instead of your decisions."],
    "coding": ["Coding before explaining the approach.", "Not testing edge cases before submitting."],
}
ROUND_KIND = {"behavioural": "behavioural", "hr": "behavioural"}


def _kind(q: dict, round_kind: str) -> str:
    k = q.get("kind") or round_kind
    if k in APPROACH:
        return k
    return ROUND_KIND.get(round_kind, round_kind if round_kind in APPROACH else "technical")


def rule_guide(q: dict, round_kind: str) -> dict:
    kind = _kind(q, round_kind)
    guide = {
        "tests": q.get("jd_line") or "",
        "approach": APPROACH[kind],
        "mention": [p for p in (q.get("key_points") or []) if p][:6],
        "avoid": AVOID.get(kind, []),
        "sample": "",
        "ai": False,
    }
    if q.get("kind") == "coding":
        p = BY_ID.get((q.get("problem") or {}).get("id", ""))
        if p:
            guide["tests"] = f"{', '.join(p.tags)} · {p.difficulty}"
            if p.hint_complexity:
                guide["mention"] = [f"Target complexity: {p.hint_complexity}", *guide["mention"]]
            guide["code"] = sample_solution(p.id) or ""
    return guide


_NUM = re.compile(r"(?<![\w\[])\d+(?:[.,]\d+)*")


def keep_to_facts(text: str, facts: str, known_skills: set[str]) -> tuple[str, int]:
    """Numbers and tools the candidate never mentioned become [placeholders], so a sample answer can't hand them a
    made-up result or a tool they haven't used. Returns (text, how many were replaced)."""
    replaced = 0
    digits = set(_NUM.findall(facts))

    def num(m: re.Match) -> str:
        nonlocal replaced
        if m.group(0) in digits:
            return m.group(0)
        replaced += 1
        return "[X]"

    text = _NUM.sub(num, text)
    allowed = {k.lower() for k in known_skills} | {k.lower() for k in extract_skills(facts)}
    for skill in extract_skills(text):
        if skill.lower() not in allowed:
            text, n = re.subn(rf"(?<![\w+#]){re.escape(skill)}(?![\w+#])", "[a tool you used]", text, flags=re.IGNORECASE)
            replaced += n
    # Names the lexicon doesn't know (a library, a college, a company): any capitalised word or acronym mid-sentence
    # that the candidate never used.
    seen = {w.lower() for w in re.findall(r"[A-Za-z][\w.+#-]*", facts)} | allowed | _COMMON

    def name(m: re.Match) -> str:
        nonlocal replaced
        word = m.group(2)
        if word.lower().rstrip(".") in seen or word.lower() in seen:
            return m.group(0)
        replaced += 1
        return m.group(1) + "[name]"

    text = re.sub(r"((?<![.!?:\n])\s)([A-Z][\w.+#-]*[\w+#])", name, text)
    text = re.sub(r"\[name\](?:\s+\[name\])+", "[name]", text)
    return text, replaced


_COMMON = {
    "i", "i'm", "i've", "i'd", "star", "api", "apis", "rest", "sql", "ui", "ux", "crud", "http", "ok", "india", "indian", "english", "hindi",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december", "situation", "task", "action", "result", "github", "linkedin",
}


class Guide(BaseModel):
    n: int = Field(description="The question's number as given")
    tests: str = Field(description="One line: what the interviewer is really checking")
    approach: list[str] = Field(description="3-4 steps of a strong answer to THIS question")
    mention: list[str] = Field(description="3-5 specific points, terms or facts a strong answer includes")
    avoid: list[str] = Field(description="1-2 mistakes to avoid on this question")
    sample: str = Field(description="A model answer in first person, 90-160 words (for coding: the approach in words, with complexity)")


class Guides(BaseModel):
    guides: list[Guide]


SYSTEM = """You are an interview coach for Indian students and freshers. For each question from a finished mock interview,
explain how to answer it well. Rules:
- Be specific to the question, the role and the field. No generic advice.
- The sample answer is first person and uses ONLY facts from the candidate's resume and answer below. Where a strong
  answer needs a fact you don't have (college, year, a number, a result, a tool, a story), write a bracketed placeholder
  such as [your college], [number of users], [X]% or [your project]. Never invent achievements, colleges, employers,
  numbers or tools. Example: "I built [your project] in Python, which cut [task] time by [X]%."
- For coding questions, the sample explains the approach in words with time and space complexity (no code).
- Keep approach steps short (under 20 words each)."""


def _resume_facts(resume: ResumeData) -> str:
    parts = []
    if resume.skills:
        parts.append("Skills: " + ", ".join(resume.skills[:20]))
    for e in resume.experience[:4]:
        parts.append(f"Role: {e.title} at {e.organization} ({e.start}-{e.end}): " + " ".join(e.bullets[:3])[:400])
    for p in resume.projects[:4]:
        parts.append(f"Project: {p.name} ({', '.join(p.tech[:6])}): " + " ".join(p.bullets[:3])[:400])
    for e in resume.education[:2]:
        parts.append(f"Education: {e.degree} {e.school} {e.end} {e.details[:120]}")
    return "\n".join(parts) or "(no resume)"


async def build_guides(s, resume: ResumeData, user_id) -> dict[str, dict]:
    """{question id: guide}. AI in batches of six, each falling back to the rules on its own."""
    meta = s.meta or {}
    round_kind = {r["index"]: r["kind"] for r in meta.get("rounds", [])}
    job = meta.get("job") or {}
    out = {q["id"]: rule_guide(q, round_kind.get(q.get("round"), "technical")) for q in s.questions}
    facts = _resume_facts(resume)
    known = set(resume.skills) | {t for p in resume.projects for t in p.tech} | {t for e in resume.experience for t in e.tech}
    batch: list[tuple[int, dict]] = list(enumerate(s.questions, 1))
    for start in range(0, len(batch), 6):
        chunk = batch[start : start + 6]
        lines = []
        for n, q in chunk:
            text = q["q"] if q.get("kind") != "coding" else (q.get("problem") or {}).get("statement", q["q"])
            ans = (s.answers or {}).get(q["id"], "")
            lines.append(
                f"Q{n} [{q.get('round_name', '')} · {q.get('kind', '')}]: {text[:700]}\n"
                f"  Tests: {q.get('jd_line', '')}\n"
                + (f"  Strong answers cover: {', '.join(q['key_points'])}\n" if q.get("key_points") else "")
                + (f"  Candidate's answer: {untrusted.wrap(ans[:500], 'interview_answer')}\n" if ans and q.get("kind") != "coding" else "")
            )
        try:
            res = await get_llm().structured(
                agent="interviewer",
                tier="fast",
                schema=Guides,
                ctx=CallContext(user_id=user_id),
                max_tokens=3500,
                system=SYSTEM,
                prompt=(
                    f"Role: {job.get('title', '')} at {job.get('company', '')} · Field: {meta.get('industry_name', '')} · Level: {meta.get('level', 'intern')}\n"
                    f"Candidate's resume facts:\n{facts}\n\nQuestions:\n" + "\n".join(lines)
                ),
            )
        except (LLMUnavailable, LLMOutputError) as exc:
            log.info("interview.guides_offline", reason=str(exc)[:200])
            continue
        by_n = {g.n: g for g in res.guides}
        for n, q in chunk:
            g = by_n.get(n)
            if not g or not g.sample.strip():
                continue
            if q.get("kind") != "coding":
                # Facts the sample may use: the resume, the question itself, and what the candidate said.
                seen = "\n".join([facts, q["q"], q.get("jd_line", ""), " ".join(q.get("key_points") or []), (s.answers or {}).get(q["id"], ""), job.get("title", ""), job.get("company", ""), meta.get("industry_name", "")])
                g.sample, _ = keep_to_facts(g.sample, seen, known)
                g.mention = [keep_to_facts(m, seen, known)[0] for m in g.mention]
                g.approach = [keep_to_facts(a, seen, known)[0] for a in g.approach]
            guide = out[q["id"]]
            guide.update(
                tests=g.tests.strip() or guide["tests"],
                approach=[a.strip() for a in g.approach if a.strip()][:5] or guide["approach"],
                mention=list(dict.fromkeys([*guide["mention"][:1], *(m.strip() for m in g.mention if m.strip())]))[:6] if q.get("kind") == "coding" else [m.strip() for m in g.mention if m.strip()][:6] or guide["mention"],
                avoid=[a.strip() for a in g.avoid if a.strip()][:3] or guide["avoid"],
                sample=re.sub(r"\s+", " ", g.sample).strip(),
                ai=True,
            )
    return out

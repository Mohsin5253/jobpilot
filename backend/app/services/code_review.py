"""The AI code reviewer for coding rounds: reads the candidate's code, the test results from their browser and their
explanation, and returns what a senior interviewer would say: is it correct, what's the complexity, what did they
miss, and how to improve it.

Ground rules:
- Test evidence wins. If the code ran and failed tests, the verdict can't be "correct"; if every test passed, it
  can't be "incorrect". The AI explains why, but doesn't overrule what actually ran.
- Java and C++ don't run in the browser, so their verdict is the AI's judgement alone and is labelled that way.
- Without an AI available, a rule-based review still gives a verdict from the tests plus static checks (nested
  loops against the expected complexity, naming, comments, length).
"""

import re

from pydantic import BaseModel, Field

from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.services.coding_bank import BY_ID, Problem

LANG_NAME = {"python": "Python", "javascript": "JavaScript", "java": "Java", "cpp": "C++"}
RUNNABLE = {"python", "javascript"}


class Review(BaseModel):
    verdict: str = Field(description="correct | partially correct | incorrect")
    summary: str = Field(description="Two sentences: does it solve the problem, and the most important thing to fix")
    time_complexity: str = Field(description="Big-O time of THIS code, e.g. O(n log n)")
    space_complexity: str = Field(description="Big-O extra space of THIS code")
    optimal: bool = Field(description="Is this the expected optimal complexity for the problem?")
    bugs: list[str] = Field(default_factory=list, max_length=5, description="Concrete bugs, citing the line or construct")
    edge_cases_missed: list[str] = Field(default_factory=list, max_length=5)
    code_quality: list[str] = Field(default_factory=list, max_length=4, description="Naming, structure, readability notes")
    improvements: list[str] = Field(default_factory=list, max_length=5, description="Actionable next steps, most important first")
    correctness: int = Field(ge=1, le=5)
    efficiency: int = Field(ge=1, le=5)
    quality: int = Field(ge=1, le=5)
    communication: int = Field(ge=1, le=5, description="How well the written approach explains the idea and complexity")


SYSTEM = """You are a senior engineer reviewing a candidate's solution in a coding interview for an Indian tech internship or
fresher role. Be precise, kind and concrete. Judge THIS code, not what it could be.
- Use the test results: if tests failed, find the bug that causes it; if all passed, don't invent failures.
- State the actual time and space complexity of the code and whether it meets the expected one.
- Point to specific lines or constructs. Never rewrite the full solution; at most show a one-line fix.
- Score 1-5: correctness, efficiency (vs the expected complexity), quality (names, structure), communication (their
  written approach: idea, complexity, edge cases)."""


def _nested_loops(code: str, lang: str) -> int:
    """Rough depth of nested loops (a cheap complexity signal for the offline review)."""
    depth = best = 0
    if lang == "python":
        stack: list[int] = []
        for line in code.splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            ind = len(line) - len(line.lstrip())
            while stack and ind <= stack[-1]:
                stack.pop()
            if re.match(r"\s*(for|while)\b", line):
                stack.append(ind)
                best = max(best, len(stack))
        return best
    for tok in re.findall(r"\b(for|while)\b|[{}]", code):
        if tok in ("for", "while"):
            depth += 1
            best = max(best, depth)
        elif tok == "}" and depth:
            depth -= 1
    return best


def offline_review(p: Problem, lang: str, code: str, approach: str, results: dict) -> dict:
    ran = bool(results.get("ran"))
    passed, total = int(results.get("passed", 0)), int(results.get("total", 0))
    body = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith(("#", "//"))]
    empty = len(body) <= 2 or ("write your solution here" in code and len(body) <= 3)
    if empty:
        verdict, corr = "incorrect", 1
    elif ran:
        verdict = "correct" if total and passed == total else "partially correct" if passed else "incorrect"
        corr = 5 if verdict == "correct" else max(1, round(1 + 3 * passed / max(total, 1)))
    else:
        verdict, corr = "not verified", 3
    loops = _nested_loops(code, lang)
    expects_linear = "O(n)" in p.hint_complexity and "log" not in p.hint_complexity.split("O(n)")[0]
    eff = 2 if (loops >= 2 and expects_linear) else 4 if loops <= 1 else 3
    short_names = len(re.findall(r"\b(?:let|var|const|int|auto)?\s*\b[a-z]\b\s*=", code))
    quality = 4 - (short_names > 4) - (len(body) > 60)
    comm = 1 if not approach.strip() else 3 + ("o(" in approach.lower()) + (len(approach.split()) > 25)
    improvements = []
    if verdict != "correct":
        improvements.append("Trace a failing test by hand before changing code, then fix the first wrong value you find.")
    if eff <= 2:
        improvements.append(f"Your loops look nested; the expected solution is {p.hint_complexity}. Look for a hash map, two pointers or sorting.")
    if comm <= 3:
        improvements.append("Before coding, write your approach in 2-3 lines with its time and space complexity, as interviewers expect you to say it aloud.")
    if quality < 4:
        improvements.append("Use descriptive names (seen, count, left/right) instead of single letters.")
    return {
        "verdict": verdict,
        "summary": ("All tests passed." if verdict == "correct" else f"{passed} of {total} tests passed." if ran else "Not run in the browser for this language; judged from the code.") + (" The approach looks slower than expected." if eff <= 2 else ""),
        "time_complexity": "unknown (AI review unavailable)",
        "space_complexity": "unknown",
        "optimal": eff >= 4,
        "bugs": [f"Failed on input {f.get('args')}: expected {f.get('expected')}, got {f.get('got', f.get('error'))}" for f in (results.get("failures") or [])[:3]],
        "edge_cases_missed": [],
        "code_quality": [],
        "improvements": improvements or ["Clean solution. Next, try the follow-up: can you do it with less memory?"],
        "correctness": corr,
        "efficiency": eff,
        "quality": max(1, quality),
        "communication": min(5, comm),
        "ai": False,
    }


def _clamp_to_tests(r: dict, results: dict, lang: str) -> dict:
    """The tests decide correctness whenever they actually ran."""
    if lang in RUNNABLE and results.get("ran") and results.get("total"):
        passed, total = int(results["passed"]), int(results["total"])
        if passed == total:
            r["verdict"] = "correct"
            r["correctness"] = max(r["correctness"], 4)
        elif passed == 0:
            r["verdict"] = "incorrect"
            r["correctness"] = min(r["correctness"], 2)
        else:
            r["verdict"] = "partially correct"
            r["correctness"] = min(max(r["correctness"], 2), 3)
    elif lang not in RUNNABLE:
        r["verified"] = False
    return r


async def review(problem_id: str, lang: str, code: str, approach: str, results: dict, user_id) -> dict:
    p = BY_ID[problem_id]
    results = {**results, "ran": bool(results.get("ran")) and lang in RUNNABLE}
    base = offline_review(p, lang, code, approach, results)
    if base["verdict"] == "incorrect" and base["correctness"] == 1 and len(code.strip()) < 80:
        out = base  # nothing written yet: no need to ask the AI
    else:
        try:
            failures = "\n".join(f"- input {f.get('args')}: expected {f.get('expected')}, got {f.get('got', f.get('error'))}" for f in (results.get("failures") or [])[:5])
            res = await get_llm().structured(
                agent="interviewer",
                tier="smart",
                schema=Review,
                ctx=CallContext(user_id=user_id),
                max_tokens=1200,
                system=SYSTEM,
                prompt=(
                    f"Problem: {p.title} ({p.difficulty})\n{p.statement}\nExpected complexity: {p.hint_complexity}\n\n"
                    f"Language: {LANG_NAME.get(lang, lang)}\n<code>\n{code[:8000]}\n</code>\n\n"
                    f"Candidate's written approach: {approach.strip()[:1500] or '(none given)'}\n\n"
                    + (f"Browser test run: {results.get('passed')}/{results.get('total')} passed.\n{failures}" if results["ran"] else "The code was not executed (language not runnable in the browser): judge it by reading.")
                ),
            )
            out = {**res.model_dump(), "ai": True}
            out["verdict"] = out["verdict"].lower().strip()
            if out["verdict"] not in ("correct", "partially correct", "incorrect"):
                out["verdict"] = base["verdict"]
            if not out["bugs"] and base["bugs"]:
                out["bugs"] = base["bugs"]
        except (LLMUnavailable, LLMOutputError):
            out = base
    out = _clamp_to_tests(out, results, lang)
    out["tests"] = {"ran": results["ran"], "passed": results.get("passed", 0), "total": results.get("total", 0)}
    out["language"] = lang
    out["score"] = round(0.45 * out["correctness"] + 0.25 * out["efficiency"] + 0.15 * out["quality"] + 0.15 * out["communication"], 1)
    out["tests_label"] = f"{out['tests']['passed']}/{out['tests']['total']} tests passed (run in your browser)" if results["ran"] else "Not executed: AI review only"
    out["feedback"] = (out.get("bugs") or [])[:1] + out["improvements"][:3]
    out["tests_detail"] = (results.get("failures") or [])[:5]
    return out

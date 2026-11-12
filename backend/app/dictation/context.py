"""The context collector (Flow's main accuracy lever), for a spoken interview answer.

A desktop dictation app reads the focused app, the text around the cursor and the names on screen. In a mock
interview, the "screen" is the interview itself, so the context is:

- the company and role being interviewed for, the round, and the question (names and terms the answer will use);
- the answer typed or dictated so far: the text before the cursor (style, and the terms already used) and after it;
- in a coding round, the problem statement and the identifiers near the cursor (getUserById, max_profit), which also
  switches the formatting style to code.

Collected in well under 50 ms from data already in hand; it never calls a model.
"""

import re
from dataclasses import dataclass, field

from app.skills import extract_skills

BEFORE_CHARS = 600
AFTER_CHARS = 200

_IDENT = re.compile(r"\b(?:[a-z]+(?:[A-Z][a-z0-9]*)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
# Runs of capitalised words that aren't just a sentence start: "Rizvi College", "Google Cloud", "HackerRank".
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][\w&+.-]*[A-Za-z0-9+#](?:\s+(?:of\s+)?[A-Z][\w&+.-]*[A-Za-z0-9+#]){0,3})")
_STOP = set("I I'm I've I'll The A An In On At For To And Or But So If When What Why How Which Who Tell Describe Walk Give Explain Your You We Our My It This That".split())


@dataclass
class AnswerContext:
    style: str = "interview"  # interview | code
    screen_terms: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    before: str = ""
    after: str = ""

    @property
    def style_sample(self) -> str:
        """The last ~25 words the candidate said or typed: the best style sample for Whisper is their own voice."""
        words = self.before.split()
        return " ".join(words[-25:]) if len(words) >= 6 else ""

    @property
    def continues_sentence(self) -> bool:
        """The cursor is mid-sentence, so the dictated text should continue it (no capital, no new sentence)."""
        b = self.before.rstrip()
        return bool(b) and not re.search(r"[.!?:\n]$", b)


def proper_nouns(text: str) -> list[str]:
    out = []
    for m in _PROPER.finditer(text or ""):
        t = m.group(1).strip(" .")
        if t.split()[0] in _STOP and len(t.split()) == 1:
            continue
        if t.split()[0] in _STOP:
            t = " ".join(t.split()[1:])
        if len(t) >= 2:
            out.append(t)
    return list(dict.fromkeys(out))


def identifiers(text: str) -> list[str]:
    return list(dict.fromkeys(_IDENT.findall(text or "")))[:30]


def collect(
    question: str = "",
    before: str = "",
    after: str = "",
    company: str = "",
    role: str = "",
    round_name: str = "",
    kind: str = "",
    problem: dict | None = None,
) -> AnswerContext:
    before, after = (before or "")[-BEFORE_CHARS:], (after or "")[:AFTER_CHARS]
    problem = problem or {}
    code = kind == "coding" or bool(problem)
    statement = " ".join(str(problem.get(k) or "") for k in ("title", "statement", "signature"))
    terms: list[str] = []
    for t in (company, role):
        if t and t.strip():
            terms.append(t.strip())
    terms += proper_nouns(question) + extract_skills(f"{question} {statement}")
    # Terms the candidate already used in this answer are likely to come up again.
    terms += proper_nouns(before) + extract_skills(before)
    idents = identifiers(f"{statement} {before} {after}") if code else []
    seen: set[str] = set()
    uniq = []
    for t in terms:
        k = t.lower()
        if k not in seen and len(t) <= 60:
            seen.add(k)
            uniq.append(t)
    return AnswerContext(style="code" if code else "interview", screen_terms=uniq[:40], identifiers=idents, before=before, after=after)

"""Learning from corrections (Flowtype's auto-learn). When an answer is submitted, each dictated take is compared with
what the candidate finally submitted; if they corrected a word we got wrong ("Kavia" -> "Kavya"), the corrected
spelling joins their dictionary, so the next dictation gets it right.

Both texts are used in memory only and never stored. A correction is learned only when it looks like a mishearing of
a name or term (it sounds or is spelled like what we wrote), not a rewrite."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from app.dictation.matcher import sound_score
from app.services.speech_vocab import COMMON, _norm

MAX_LEARNED = 100


@dataclass
class LearnResult:
    edit_rate: float
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (what we wrote, what they changed it to)


def word_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, wb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb))
        prev = cur
    return prev[-1]


def locate(dictated: str, final: str) -> str | None:
    """The part of the final answer that is (a corrected version of) the dictated take: a fuzzy alignment, widened by
    a few words, then trimmed at the word level to where it stops matching."""
    if not dictated.strip() or not final:
        return None
    al = fuzz.partial_ratio_alignment(dictated, final, score_cutoff=55)
    if al is None:
        return None
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", final)]
    first = next((k for k, (s, e) in enumerate(spans) if e > al.dest_start), 0)
    last = max((k for k, (s, e) in enumerate(spans) if s < al.dest_end), default=len(spans) - 1)
    first, last = max(0, first - 3), min(len(spans) - 1, last + 3)
    wide = [final[s:e] for s, e in spans[first : last + 1]]
    na, nb = [_norm(w) for w in re.findall(r"\S+", dictated)], [_norm(w) for w in wide]
    ops = SequenceMatcher(None, na, nb, autojunk=False).get_opcodes()
    while ops and ops[0][0] == "insert":
        ops.pop(0)
    while ops and ops[-1][0] == "insert":
        ops.pop()
    if not ops:
        return None
    return " ".join(wide[ops[0][3] : ops[-1][4]])


def _termlike(phrase: str) -> bool:
    words = phrase.split()
    if not words or all(w.lower().strip(".,!?") in COMMON for w in words):
        return False
    return any(re.search(r"^[A-Z]|[a-z][A-Z]|\d|[+#]", w) for w in words)


def learn(dictated: str, final: str, max_edit_rate: float = 0.5) -> LearnResult | None:
    region = locate(dictated, final)
    if region is None:
        return None
    a, b = re.findall(r"\S+", dictated), re.findall(r"\S+", region)
    na, nb = [_norm(w) for w in a], [_norm(w) for w in b]
    rate = word_distance(na, nb) / max(1, len(na))
    res = LearnResult(edit_rate=round(rate, 3))
    if rate > max_edit_rate:
        return res  # a rewrite, not a correction
    for op, i1, i2, j1, j2 in SequenceMatcher(None, na, nb, autojunk=False).get_opcodes():
        if op != "replace" or i2 - i1 > 3 or j2 - j1 > 3:
            continue
        wrote = " ".join(a[i1:i2]).strip(".,!?;:\"'")
        fixed = " ".join(b[j1:j2]).strip(".,!?;:\"'")
        if not _termlike(fixed) or _norm(wrote) == _norm(fixed) or len(fixed) > 60:
            continue
        if sound_score(wrote, fixed) >= 0.6 or fuzz.ratio(_norm(wrote), _norm(fixed)) >= 60:
            res.corrections.append((wrote, fixed))
    return res


def merge_learned(current: list[str], new: list[str], own: list[str]) -> list[str]:
    """Newest first, no duplicates of each other or of the words the candidate added themselves, capped."""
    seen = {w.lower() for w in own}
    out = []
    for w in [*new, *current]:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out[:MAX_LEARNED]

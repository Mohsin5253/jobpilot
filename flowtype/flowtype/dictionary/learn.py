"""Learning from corrections. A few seconds after a paste we read the field again; if you corrected a word we got
wrong ("Kavia" -> "Kavya"), the corrected spelling joins your dictionary, so the next dictation gets it right. The
same read gives the Edit Rate: how much of what we pasted you changed.

The pasted text is kept in memory only until that read. A correction is learned only when it looks like a
mishearing (it sounds or is spelled like what we wrote) of a name or term, not a rewrite."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from flowtype.dictionary.matcher import sound_score
from flowtype.dictionary.phonetic import COMMON, _norm
from flowtype.eval.wer import word_distance


@dataclass
class LearnResult:
    edit_rate: float
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (what we wrote, what you changed it to)


def locate(pasted: str, field_text: str) -> str | None:
    """The part of the field that is (a corrected version of) what we pasted: a rough fuzzy alignment, widened by a
    few words, then trimmed at the word level to where it stops matching."""
    if not pasted.strip() or not field_text:
        return None
    al = fuzz.partial_ratio_alignment(pasted, field_text, score_cutoff=55)
    if al is None:
        return None
    spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", field_text)]
    first = next((k for k, (s, e) in enumerate(spans) if e > al.dest_start), 0)
    last = max((k for k, (s, e) in enumerate(spans) if s < al.dest_end), default=len(spans) - 1)
    first, last = max(0, first - 3), min(len(spans) - 1, last + 3)
    wide = [field_text[s:e] for s, e in spans[first : last + 1]]
    na, nb = [_norm(w) for w in re.findall(r"\S+", pasted)], [_norm(w) for w in wide]
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


def learn(pasted: str, field_text: str, max_edit_rate: float = 0.5) -> LearnResult | None:
    region = locate(pasted, field_text)
    if region is None:
        return None
    a, b = re.findall(r"\S+", pasted), re.findall(r"\S+", region)
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
        if not _termlike(fixed) or _norm(wrote) == _norm(fixed):
            continue
        if sound_score(wrote, fixed) >= 0.6 or fuzz.ratio(_norm(wrote), _norm(fixed)) >= 60:
            res.corrections.append((wrote, fixed))
    return res

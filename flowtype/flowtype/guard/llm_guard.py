"""Guardrails for the LLM clean-up (ported from JobPilot's validator). LLMs have high recall and low precision: they
"fix" words that were already right, add names, or answer the dictation instead of formatting it. Every rewrite is
checked against what was said; anything that fails falls back to the deterministic text."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from flowtype.dictionary.phonetic import _sound

_FILLER = re.compile(r"(?<![\w'])(?:u+m+|u+h+|e+r+m+|h+m+|a+h+|mhm)(?![\w'])[,.]?\s*", re.I)
_STUTTER = re.compile(r"\b(\w+)(?:\s+\1\b)+", re.I)
_ANSWERY = re.compile(r"^\s*(sure|certainly|of course|here'?s|here is|as an ai|i'?d be happy|great question|absolutely[,!]|i can'?t|i cannot|sorry,? (but )?i)\b", re.I)
_WORD = re.compile(r"[\w'+#./@-]+")

MAX_EDIT = 0.35
MIN_RATIO, MAX_RATIO = 0.5, 1.3


def strip_fillers(text: str) -> str:
    """Only the unambiguous fillers (um, uh, erm, hmm) and stutters ("I I I" -> "I"); "like" and "you know" can be
    real words, so only the model removes those."""
    t = _FILLER.sub("", text)
    t = _STUTTER.sub(r"\1", t)
    t = re.sub(r"\s+([,.?!])", r"\1", t)
    t = re.sub(r"^[,.\s]+", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:1].upper() + t[1:] if t else t


def has_fillers(text: str) -> bool:
    return bool(_FILLER.search(text) or _STUTTER.search(text) or re.search(r"\b(no wait|sorry|i mean|actually,? no|scratch that)\b", text, re.I))


def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000, "billion": 1_000_000_000}


def spoken_numbers(text: str) -> set[str]:
    """Every number the speaker said, as digits: "two hundred" -> 200, "one point five" -> 1.5, "five lakh" -> 500000."""
    found = {n.replace(",", "").lstrip("0") or "0" for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    digits = re.sub(r"[a-z]+", lambda m: str(_UNITS[m.group(0)]) if m.group(0) in _UNITS else m.group(0), text.lower())
    found |= {f"{a.lstrip('0') or '0'}.{b}" for a, b in re.findall(r"(\d+) point (\d+)", digits)}
    total = cur = 0
    started = False
    prev = ""

    def flush():
        nonlocal total, cur, started
        if started:
            found.add(str(total + cur))
            for scale in (100, 1000):  # "two hundred" may be written "2 hundred"
                if (total + cur) % scale == 0 and total + cur > scale:
                    found.add(str((total + cur) // scale))
        total = cur = 0
        started = False

    for w in [*re.findall(r"[a-z]+|\d+|[,.;:!?]", text.lower()), "."]:
        if w in _UNITS or w in _TENS:
            v = _UNITS.get(w, 0) + _TENS.get(w, 0)
            found.add(str(v))  # each word alone too: "four thirty" -> 4:30
            # "five five" or "twenty thirty" are two numbers; "twenty five" and "hundred and five" are one.
            if started and not (prev in _TENS and w in _UNITS and v < 10) and prev not in _SCALES and prev != "and":
                flush()
            cur += v
            started = True
        elif w in _SCALES and (started or w in ("hundred", "thousand")):
            scale = _SCALES[w]
            cur = max(cur, 1) * scale
            if scale >= 1000:
                total, cur = total + cur, 0
            started = True
        elif w == "and" and started and prev in _SCALES:
            pass
        else:
            flush()
            if w.isdigit():
                found.add(w.lstrip("0") or "0")
        prev = w
    return found


SOUNDS_LIKE = 0.8  # measured: real fixes 0.84-0.95 ("fast RP" -> FastAPI, "cooper nets" -> Kubernetes); invented names <= 0.5


def sounds_like_said(term: str, said_words: list[str]) -> bool:
    """Whether `term` sounds and is spelled like a run of 1-4 words the speaker said."""
    from flowtype.dictionary.matcher import match_score

    return any(match_score(" ".join(said_words[i : i + n]), term) >= SOUNDS_LIKE
               for n in (1, 2, 3, 4) for i in range(max(0, len(said_words) - n + 1)))


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    edit: float = 0.0
    ratio: float = 1.0


def check(transcript: str, output: str, known_terms: list[str], max_edit: float = MAX_EDIT) -> Verdict:
    """Reject a rewrite that moved too far from what was said, added a name, term or number nobody said, or reads
    like a reply. Compared against the transcript with the unambiguous fillers removed."""
    base = strip_fillers(transcript)
    a = [_norm(w) for w in _WORD.findall(base) if _norm(w)]
    b = [_norm(w) for w in _WORD.findall(output) if _norm(w)]
    parts = lambda t: [p for w in _WORD.findall(t) for p in re.findall(r"[a-z]+|\d+", w.lower())]  # noqa: E731
    if not b:
        return Verdict(not a or len(a) <= 2, "empty output" if a and len(a) > 2 else "")
    ratio = len(b) / max(1, len(a))
    # Number words count as their digits, so "four thirty" -> "4:30" isn't an edit.
    canon = lambda ws: [str(_UNITS.get(w, _TENS.get(w, w))) for w in ws]  # noqa: E731
    edit = 1 - SequenceMatcher(None, canon(parts(base)), parts(output)).ratio()
    if _ANSWERY.search(output) and not _ANSWERY.search(base):
        return Verdict(False, "reads like a reply", edit, ratio)
    if not MIN_RATIO <= ratio <= MAX_RATIO and abs(len(b) - len(a)) > 2:
        return Verdict(False, f"length ratio {ratio:.2f}", edit, ratio)
    if edit > max_edit and len(a) > 4:
        return Verdict(False, f"changed {edit:.0%} of the words", edit, ratio)
    said = {_norm(w) for w in _WORD.findall(transcript)} | {_sound(w) for w in _WORD.findall(transcript)}
    said_joined = _norm(transcript)
    known = {_norm(w) for t in known_terms for w in t.split()} | {_sound(w) for t in known_terms for w in t.split()}
    said_numbers = spoken_numbers(transcript)
    said_words = [w.strip(".,;:!?'\"()") for w in _WORD.findall(transcript)]
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", output):
        num = m.group(0).rstrip(",")
        n = num.replace(",", "").lstrip("0") or "0"
        line_start = output.rfind("\n", 0, m.start()) + 1
        is_list_marker = output[line_start : m.start()].strip() == "" and output[m.end() : m.end() + 1] in (".", ")")
        is_zero_minutes = n == "0" and num == "00" and output[m.start() - 1 : m.start()] == ":"  # "ten" -> 10:00
        if n not in said_numbers and not is_list_marker and not is_zero_minutes:  # list numbers 1. 2. 3. are formatting
            return Verdict(False, f"added the number {num}", edit, ratio)
    for i, w in enumerate(_WORD.findall(output)):
        bare = w.strip(".,;:!?'\"()")
        if re.fullmatch(r"[\d,.:%₹$]+(?:st|nd|rd|th|k|pm|am)?", bare, re.I):
            continue
        if len(bare) < 3 or not (bare[0].isupper() or re.search(r"[A-Z].*[A-Z]|\d|[+#]", bare[1:])):
            continue
        n, s = _norm(bare), _sound(bare)
        if n in said or s in said or n in known or s in known or (len(n) >= 5 and n in said_joined):
            continue
        prev = output[: output.find(w)].rstrip()
        if i == 0 or prev.endswith((".", "?", "!", ":", "\n")) or re.match(r"^\d+[.)]", bare):
            continue  # a capital at a sentence start is formatting, not a new name
        if sounds_like_said(bare, said_words):
            continue  # a spelling fix of what was heard ("fast RP" -> FastAPI), not an invented name
        return Verdict(False, f"added '{bare}'", edit, ratio)
    return Verdict(True, "", edit, ratio)

"""Phonetic pre-pass: replace a phrase in the transcript that sounds like one of your dictionary terms with the
term ("Mohasin Sidpurwala" -> "Mohsin Sidhpurwala", "cooper netties" -> "Kubernetes").

A candidate window of words is compared with each term three ways: spelling (rapidfuzz), Double Metaphone codes
(English-style sound), and a sound key tuned for Indian names (vowels collapsed, aspirates merged). Common words are
never rewritten, and a window never starts or ends on a small function word ("I'm Mohsen" isn't a misheard name)."""

import re
from dataclasses import dataclass
from functools import lru_cache

from metaphone import doublemetaphone
from rapidfuzz import fuzz

from flowtype.dictionary.phonetic import COMMON, EDGE, _norm, _sound


@lru_cache(maxsize=4096)
def metaphone_key(phrase: str) -> tuple[str, str]:
    """Primary and alternate Double Metaphone codes of a phrase, word codes joined."""
    prim, alt = [], []
    for w in phrase.split():
        p, a = doublemetaphone(w)
        prim.append(p)
        alt.append(a or p)
    return "".join(prim), "".join(alt)


def sound_score(heard: str, term: str) -> float:
    """0..1: how alike two phrases sound."""
    hp, ha = metaphone_key(heard)
    tp, ta = metaphone_key(term)
    meta = max(fuzz.ratio(x, y) for x in (hp, ha) for y in (tp, ta) if x and y) / 100 if (hp or ha) and (tp or ta) else 0.0
    indian = fuzz.ratio(_sound(heard), _sound(term)) / 100
    return max(meta, indian)


def match_score(heard: str, term: str) -> float:
    spell = fuzz.ratio(_norm(heard), _norm(term)) / 100
    sound = sound_score(heard, term)
    # Sound alone isn't enough ("sea" and "C" sound the same): it must also be spelled somewhat alike.
    return max(spell, (spell + sound) / 2 if sound >= 0.85 else 0.0, sound * 0.95 if spell >= 0.6 else 0.0)


@dataclass
class Fix:
    heard: str
    fixed: str
    score: float


def correct(text: str, vocab: list[str]) -> tuple[str, list[dict]]:
    """(corrected text, [{heard, fixed}]). Longest terms first, so "Rizvi College of Engineering" beats "Rizvi"."""
    if not text or not vocab:
        return text, []
    tokens = re.findall(r"\S+", text)
    bare = [re.sub(r"^\W+|\W+$", "", t) for t in tokens]
    fixes: list[dict] = []
    for term in sorted(dict.fromkeys(vocab), key=lambda v: -len(v.split())):
        n = len(term.split())
        if n > 6 or len(_norm(term)) < 3:
            continue
        joined = " ".join(bare)
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", joined):
            continue  # already spelled right
        best: tuple[float, int, int, str] | None = None
        for size in sorted({n, n + 1, max(1, n - 1)}):
            for i in range(0, len(tokens) - size + 1):
                window = bare[i : i + size]
                if not all(window) or all(w.lower() in COMMON for w in window):
                    continue
                if size > 1 and (window[0].lower() in EDGE or window[-1].lower() in EDGE):
                    continue
                heard = " ".join(window)
                if heard.lower() == term.lower():
                    score = 1.0  # right word, wrong capitals
                else:
                    if any(w.lower() in COMMON for w in window) and size == 1:
                        continue
                    score = match_score(heard, term)
                need = 0.88 if len(_norm(term)) < 6 else 0.8
                if score >= need and (best is None or score > best[0]):
                    best = (score, i, size, heard)
        if best:
            _, i, size, heard = best
            lead = re.match(r"^\W*", tokens[i]).group(0)
            trail = re.search(r"\W*$", tokens[i + size - 1]).group(0)
            tokens[i : i + size] = [f"{lead}{term}{trail}"]
            bare[i : i + size] = [term]
            fixes.append({"heard": heard, "fixed": term})
    return " ".join(tokens), fixes

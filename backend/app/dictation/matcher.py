"""Flowtype's sound match: replace a phrase in the transcript that sounds like one of your dictionary terms with the
term ("Mohasin Sidpurwala" -> "Mohsin Sidhpurwala", "cooper netties" -> "Kubernetes").

A window of words is compared with each term three ways: spelling (rapidfuzz), Double Metaphone codes (English-style
sound), and a sound key tuned for Indian names (vowels collapsed, aspirates merged). Common words are never
rewritten, and a window never starts or ends on a small function word ("I'm Mohsen" isn't a misheard name)."""

import re
from functools import lru_cache

from metaphone import doublemetaphone
from rapidfuzz import fuzz

from app.services.speech_vocab import COMMON, EDGE, _norm, _sound

SOUNDS_LIKE = 0.8  # measured on live output: real fixes 0.84-0.95 ("fast RP" -> FastAPI); invented names <= 0.5


@lru_cache(maxsize=4096)
def metaphone_key(phrase: str) -> tuple[str, str]:
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
    return max(meta, fuzz.ratio(_sound(heard), _sound(term)) / 100)


def match_score(heard: str, term: str) -> float:
    spell = fuzz.ratio(_norm(heard), _norm(term)) / 100
    sound = sound_score(heard, term)
    # Sound alone isn't enough ("sea" and "C" sound the same): it must also be spelled somewhat alike.
    return max(spell, (spell + sound) / 2 if sound >= 0.85 else 0.0, sound * 0.95 if spell >= 0.6 else 0.0)


def sounds_like_said(term: str, said_words: list[str]) -> bool:
    """Whether `term` sounds and is spelled like a run of 1-4 words the speaker said."""
    return any(match_score(" ".join(said_words[i : i + n]), term) >= SOUNDS_LIKE for n in (1, 2, 3, 4) for i in range(max(0, len(said_words) - n + 1)))


def _spoken_words(term: str) -> int:
    """How many words a term is spoken as: "getUserById" and "max_profit" are said "get user by id", "max profit"."""
    if " " in term.strip() or not re.search(r"[a-z][A-Z]|[A-Za-z]_[A-Za-z]", term):
        return len(term.split())
    return max(1, len(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", term)))


def correct(text: str, vocab: list[str]) -> tuple[str, list[dict]]:
    """(corrected text, [{heard, fixed}]). Longest terms first, so "Rizvi College of Engineering" beats "Rizvi"."""
    if not text or not vocab:
        return text, []
    tokens = re.findall(r"\S+", text)
    bare = [re.sub(r"^\W+|\W+$", "", t) for t in tokens]
    fixes: list[dict] = []
    for term in sorted(dict.fromkeys(v for v in vocab if v and v.strip()), key=lambda v: -_spoken_words(v)):
        n = _spoken_words(term)
        if n > 6 or len(_norm(term)) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", " ".join(bare)):
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
                elif size == 1 and window[0].lower() in COMMON:
                    continue
                else:
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

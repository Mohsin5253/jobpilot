"""Phonetic dictionary match (ported from JobPilot's speech_vocab.py): any phrase in the transcript that sounds like
one of your dictionary words ("Mohasin Sidpurwala", "Rizavi College") is replaced by it. Matching is by spelling
and sound, so ordinary words are never touched."""

import re
from difflib import SequenceMatcher

# Words the sound match must never rewrite (they're common, so a near-miss is a different word, not a mishearing).
COMMON = set(
    """a an and are as at be been but by can did do for from had has have he her his i i'm in is it its me my of on or
    our she so that the their them then there they this to was we were what when which who will with you your also
    about after all am any because before both each few how into just like more most no not now only other out over
    same some such than too very well where while why yes year years work worked working team project projects data
    model models built build used using use made make data science engineering student college university""".split()
)


# Small words that never begin or end a misheard name ("I'm Mohsen", "Mumbai in").
EDGE = set("a an and are as at by for from i i'm i've in is it of on or the to was we with my me".split())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _sound(s: str) -> str:
    """A rough phonetic key for Indian-English names and terms: vowels collapsed, common spelling variants merged."""
    s = _norm(s)
    for a, b in (("ph", "f"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"), ("sh", "s"), ("ck", "k"), ("q", "k"), ("z", "s"), ("w", "v"), ("ee", "i"), ("oo", "u")):
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)  # doubled letters
    return s[:1] + re.sub(r"[aeiouy]", "", s[1:])


def correct(text: str, vocab: list[str]) -> tuple[str, list[dict]]:
    """Replace phrases that sound like one of your vocabulary terms with the term. Returns (text, [{heard, fixed}])."""
    if not text or not vocab:
        return text, []
    tokens = re.findall(r"\S+", text)
    bare = [re.sub(r"^\W+|\W+$", "", t) for t in tokens]
    fixes: list[dict] = []
    # Longest terms first, so "Rizvi College of Engineering" wins over "Rizvi".
    for term in sorted(vocab, key=lambda v: -len(v.split())):
        tw = term.split()
        n = len(tw)
        if n > 6 or len(_norm(term)) < 4:
            continue
        joined = " ".join(bare)
        if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", joined):
            continue  # already spelled right
        if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", joined, re.I):
            # Right word, wrong capitals ("flask", "ai medical assistant"): use your spelling.
            for i in range(0, len(tokens) - n + 1):
                if " ".join(bare[i : i + n]).lower() == term.lower() and " ".join(bare[i : i + n]) != term:
                    lead = re.match(r"^\W*", tokens[i]).group(0)
                    trail = re.search(r"\W*$", tokens[i + n - 1]).group(0)
                    fixes.append({"heard": " ".join(bare[i : i + n]), "fixed": term})
                    tokens[i : i + n] = [f"{lead}{term}{trail}"]
                    bare[i : i + n] = [term]
                    break
            continue
        best = None
        for size in {n, n + 1, max(1, n - 1)}:
            for i in range(0, len(tokens) - size + 1):
                window = bare[i : i + size]
                if not all(window) or all(w.lower() in COMMON for w in window):
                    continue
                # A window never starts or ends on a common word: "I'm Mohsen" isn't a mishearing of a name.
                if size > 1 and (window[0].lower() in EDGE or window[-1].lower() in EDGE):
                    continue
                heard = " ".join(window)
                spell = SequenceMatcher(None, _norm(heard), _norm(term)).ratio()
                sound = SequenceMatcher(None, _sound(heard), _sound(term)).ratio()
                # Short terms need a near-exact match; names can drift more (Indian names have many spellings).
                need = 0.86 if len(_norm(term)) < 7 else 0.78
                if max(spell, sound) >= need and (best is None or max(spell, sound) > best[0]):
                    best = (max(spell, sound), i, size, heard)
        if best:
            _, i, size, heard = best
            lead = re.match(r"^\W*", tokens[i]).group(0)
            trail = re.search(r"\W*$", tokens[i + size - 1]).group(0)
            tokens[i : i + size] = [f"{lead}{term}{trail}"]
            bare[i : i + size] = [term]
            fixes.append({"heard": heard, "fixed": term})
    return " ".join(tokens), fixes



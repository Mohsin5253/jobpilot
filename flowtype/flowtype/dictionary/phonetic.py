"""Shared phonetic helpers (ported from JobPilot's speech_vocab.py): the word lists the matcher must never rewrite,
and a sound key for Indian-English names. The matcher itself is dictionary/matcher.py."""

import re

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

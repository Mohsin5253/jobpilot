"""Word error rate and Edit Rate. WER compares a transcript with a reference; Edit Rate (Phase 2) compares what we
pasted with what the user left after correcting it. Both are word-level Levenshtein distance over reference length."""

import re


def _words(s: str) -> list[str]:
    return re.findall(r"[\w'+#./-]+", s.lower())


def word_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, wb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref = _words(reference)
    return word_distance(ref, _words(hypothesis)) / max(1, len(ref))


def edit_rate(pasted: str, final: str) -> float:
    return wer(final, pasted)

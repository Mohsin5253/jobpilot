"""Whisper's known failure modes on silence and noise: stock phrases ("Thank you for watching", "Subtitles by…")
and repetition loops. Segments Whisper itself marks as unlikely speech are dropped; a loop triggers one retry
without the prompt (a biasing prompt can seed loops)."""

import re

from app.dictation.providers import ASRResult

PHANTOMS = re.compile(
    r"^\W*(thank you( (so much|very much))?( for watching)?|thanks for watching|please subscribe|like and subscribe|"
    r"subtitles? by.*|transcribed by.*|you|bye|okay|so|\.+|music|\[.*\])\W*$",
    re.I,
)
NO_SPEECH = 0.6
LOGPROB = -0.8
COMPRESSION = 2.4


def is_phantom(text: str) -> bool:
    return bool(PHANTOMS.match(text.strip()))


def has_loop(text: str, n: int = 3, repeats: int = 4) -> bool:
    """The same n-word phrase repeated `repeats`+ times in a row (Whisper's decoding loop)."""
    w = text.lower().split()
    for size in range(1, n + 1):
        for i in range(0, max(0, len(w) - size * repeats) + 1):
            chunk = w[i : i + size]
            if all(w[i + k * size : i + (k + 1) * size] == chunk for k in range(repeats)):
                return True
    return False


def clean(res: ASRResult) -> str:
    """The transcript without silent, looping or stock-phrase segments."""
    if not res.segments:
        return "" if is_phantom(res.text) else res.text.strip()
    kept = []
    for s in res.segments:
        silent = s.no_speech_prob > NO_SPEECH and s.avg_logprob < LOGPROB
        looping = s.compression_ratio > COMPRESSION
        if s.text and not silent and not looping and not is_phantom(s.text):
            kept.append(s.text)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()

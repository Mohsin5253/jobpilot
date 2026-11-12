"""Whisper's known failure modes on silence and noise (ported from JobPilot, tuned for dictation):

- stock phrases from its subtitle training data ("Thanks for watching", "Subtitles by…"): always dropped;
- short phrases that are real replies but also classic phantoms ("Thank you.", "Okay.", "Bye."): dropped only when
  Whisper itself wasn't sure there was speech;
- segments Whisper marks as unlikely speech (no_speech_prob), and repetition loops (compression_ratio > 2.4);
- a loop, or the prompt echoed back, triggers one retry without the prompt (a bias prompt can seed both)."""

import re
from dataclasses import dataclass, field

from flowtype.asr.base import ASRResult, Segment

STOCK = re.compile(
    r"^\W*(thanks? (you )?(so much |very much )?for watching|please (like,? )?(share,? )?(and )?subscribe|"
    r"(like|share) and subscribe|don'?t forget to subscribe|subtitles?( by| created by)?\b.*|transcri(bed|ption) by\b.*|"
    r"captions? by\b.*|.*\bamara\.org\b.*|(\[|\()\s*(music|applause|silence|blank_audio|inaudible|laughs?)\s*(\]|\))|"
    r"♪+.*|\.+|सब्सक्राइब.*|धन्यवाद देखने के लिए.*)\W*$",
    re.I,
)
WEAK = re.compile(r"^\W*(you|thank you( so much| very much)?|thanks|bye( bye)?|okay|ok|so|yeah|hmm+|uh+|um+|धन्यवाद)\W*$", re.I)

NO_SPEECH = 0.6
LOGPROB = -0.8
WEAK_NO_SPEECH = 0.3
WEAK_LOGPROB = -0.6
COMPRESSION = 2.4


@dataclass
class GuardResult:
    text: str
    dropped: list[str] = field(default_factory=list)  # reasons, for the log: "stock", "weak", "no_speech", "loop"


def is_stock(text: str) -> bool:
    return bool(STOCK.match(text.strip()))


def has_loop(text: str, n: int = 4, repeats: int = 4) -> bool:
    """The same 1..n-word phrase repeated `repeats`+ times in a row (Whisper's decoding loop)."""
    w = re.findall(r"\w+", text.lower())
    for size in range(1, n + 1):
        for i in range(0, max(0, len(w) - size * repeats) + 1):
            chunk = w[i : i + size]
            if all(w[i + k * size : i + (k + 1) * size] == chunk for k in range(repeats)):
                return True
    return False


def echoes_prompt(text: str, prompt: str, min_words: int = 6) -> bool:
    """Whisper sometimes returns (part of) the prompt instead of the speech."""
    if not prompt or not text:
        return False
    t, p = _words(text), _words(prompt)
    if len(t) < min_words:  # a short result counts only if it's a run of the prompt's own words
        return len(t) >= 3 and f" {' '.join(t)} " in f" {' '.join(p)} "
    grams = {tuple(p[i : i + min_words]) for i in range(len(p) - min_words + 1)}
    return any(tuple(t[i : i + min_words]) in grams for i in range(len(t) - min_words + 1))


def needs_retry(res: ASRResult, prompt: str) -> bool:
    """Retry once without the prompt when the result loops or parrots the prompt."""
    if not prompt:
        return False
    if any(s.compression_ratio > COMPRESSION for s in res.segments) or has_loop(res.text):
        return True
    return echoes_prompt(res.text, prompt)


def clean(res: ASRResult) -> GuardResult:
    """The transcript without silent, looping or stock-phrase segments."""
    segments = res.segments or [Segment(text=res.text)]
    kept: list[str] = []
    dropped: list[str] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        if s.no_speech_prob > NO_SPEECH and s.avg_logprob < LOGPROB:
            dropped.append("no_speech")
        elif s.compression_ratio > COMPRESSION or has_loop(text):
            dropped.append("loop")
        elif is_stock(text):
            dropped.append("stock")
        elif WEAK.match(text) and (s.no_speech_prob > WEAK_NO_SPEECH or s.avg_logprob < WEAK_LOGPROB):
            dropped.append("weak")
        else:
            kept.append(text)
    return GuardResult(text=re.sub(r"\s+", " ", " ".join(kept)).strip(), dropped=dropped)


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())

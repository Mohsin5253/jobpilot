"""Whisper's known failure modes on silence and noise (Flowtype's guard, tuned on live Groq output):

- stock phrases from its subtitle training data ("Thanks for watching", "Subtitles by…"): always dropped;
- short phrases that are real replies but also classic phantoms ("Thank you.", "Okay.", "Bye."): dropped only when
  Whisper itself wasn't sure there was speech;
- segments Whisper marks as unlikely speech, low-confidence segments, and repetition loops;
- a loop, or the prompt echoed back, triggers one retry without the prompt (a bias prompt can seed both).

Measured (flowtype/README, "Measured"): Groq's turbo model reports no_speech_prob = 0 even for pure noise, so
confidence comes from avg_logprob (speech -0.11..-0.37; noise -0.66..-1.64). With a bias prompt, noise comes back as
the prompt's own terms ("Razorpay, Zeta Labs, FastAPI"), which the echo check catches."""

import re
from dataclasses import dataclass, field

from app.dictation.providers import ASRResult, Segment

STOCK = re.compile(
    r"^\W*(thanks? (you )?(so much |very much )?for watching|please (like,? )?(share,? )?(and )?subscribe|"
    r"(like|share) and subscribe|don'?t forget to subscribe|subtitles?( by| created by)?\b.*|transcri(bed|ption) by\b.*|"
    r"captions? by\b.*|.*\bamara\.org\b.*|(\[|\()\s*(music|applause|silence|blank_audio|inaudible|laughs?)\s*(\]|\))|"
    r"♪+.*|\.+|सब्सक्राइब.*|धन्यवाद देखने के लिए.*)\W*$",
    re.I,
)
WEAK = re.compile(r"^\W*(you|thank you( so much| very much)?|thanks|bye( bye)?|okay|ok|so|yeah|hmm+|uh+|um+|music|धन्यवाद)\W*$", re.I)

NO_SPEECH = 0.6
LOGPROB = -0.8
WEAK_NO_SPEECH = 0.3
WEAK_LOGPROB = -0.6
COMPRESSION = 2.4
LOW_CONFIDENCE = -1.0  # avg_logprob below this is dropped whatever no_speech_prob says


@dataclass
class GuardResult:
    text: str
    dropped: list[str] = field(default_factory=list)  # reasons, for the log: stock, weak, no_speech, low_confidence, loop


def is_phantom(text: str) -> bool:
    """A stock phrase, or a short reply that Whisper also produces on silence ("Thank you.", "Bye.")."""
    t = text.strip()
    return not t or bool(STOCK.match(t) or WEAK.match(t))


def has_loop(text: str, n: int = 4, repeats: int = 4) -> bool:
    """The same 1..n-word phrase repeated `repeats`+ times in a row (Whisper's decoding loop)."""
    w = re.findall(r"\w+", text.lower())
    if len(w) < repeats:
        return False
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
    if len(t) <= 12 and set(t) <= set(p):
        return True  # nothing but the prompt's own words ("Razorpay, Zeta Labs, FastAPI" from noise)
    if len(t) < min_words:
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


def guard(res: ASRResult) -> GuardResult:
    """The transcript without silent, low-confidence, looping or stock-phrase segments, and why each was dropped."""
    segments = res.segments or [Segment(text=res.text)]
    kept: list[str] = []
    dropped: list[str] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        if s.no_speech_prob > NO_SPEECH and s.avg_logprob < LOGPROB:
            dropped.append("no_speech")
        elif s.avg_logprob < LOW_CONFIDENCE:
            dropped.append("low_confidence")
        elif s.compression_ratio > COMPRESSION or has_loop(text):
            dropped.append("loop")
        elif STOCK.match(text):
            dropped.append("stock")
        elif WEAK.match(text) and (not res.segments or s.no_speech_prob > WEAK_NO_SPEECH or s.avg_logprob < WEAK_LOGPROB):
            dropped.append("weak")  # without segments there's no confidence to go on, so a lone "Thank you." goes
        else:
            kept.append(text)
    return GuardResult(text=re.sub(r"\s+", " ", " ".join(kept)).strip(), dropped=dropped)


def clean(res: ASRResult) -> str:
    return guard(res).text


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())

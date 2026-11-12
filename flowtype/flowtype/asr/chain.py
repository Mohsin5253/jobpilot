"""ASR combinators. The pipeline sees one ASRProvider; these decide which engine actually runs.

- FallbackASR: the primary (Groq) and, when it fails, the fallback (local). After a failure the primary is skipped
  for `breaker_s`, so being offline costs one timeout, not one per dictation.
- DualASR (max-accuracy mode): two engines in parallel; the more confident transcript wins."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

import numpy as np

from flowtype.asr.base import ASRError, ASRResult
from flowtype.eval.wer import wer


class FallbackASR:
    def __init__(self, primary, fallback, breaker_s: float = 60.0, clock=time.monotonic):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.breaker_s = breaker_s
        self._clock = clock
        self._down_until = 0.0
        self._lock = threading.Lock()

    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult:
        if self._clock() >= self._down_until:
            try:
                return self.primary.transcribe(audio, prompt, lang)
            except ASRError:
                with self._lock:
                    self._down_until = self._clock() + self.breaker_s
        return self.fallback.transcribe(audio, prompt, lang)


def confidence(res: ASRResult) -> float:
    """Mean avg_logprob weighted by segment length (higher = more confident)."""
    segs = [s for s in res.segments if s.text]
    if not segs:
        return -10.0 if not res.text else -1.0
    total = sum(len(s.text) for s in segs)
    return sum(s.avg_logprob * len(s.text) for s in segs) / max(1, total)


def pick(a: ASRResult | None, b: ASRResult | None, vocab: list[str] | None = None) -> ASRResult:
    if a is None or b is None:
        res = a or b
        if res is None:
            raise ASRError("both engines failed")
        return res
    if wer(a.text, b.text) <= 0.1:
        return a  # they agree: keep the primary's spelling

    def score(r: ASRResult) -> float:
        hits = sum(1 for v in vocab or [] if v.lower() in r.text.lower())
        return confidence(r) + 0.05 * hits

    return a if score(a) >= score(b) else b


class DualASR:
    def __init__(self, a, b, vocab_fn=lambda: [], extra_wait_s: float = 1.5):
        self.a, self.b = a, b
        self.name = f"dual({a.name}+{b.name})"
        self.vocab_fn = vocab_fn
        self.extra_wait_s = extra_wait_s
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dual-asr")

    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult:
        fa = self._pool.submit(self.a.transcribe, audio, prompt, lang)
        fb = self._pool.submit(self.b.transcribe, audio, prompt, lang)
        ra = _get(fa, None)
        rb = _get(fb, self.extra_wait_s)  # don't wait long for the slower engine once the first is in
        if ra is None and rb is None:
            rb = _get(fb, None)
        res = pick(ra, rb, self.vocab_fn())
        res.model = f"{res.model} (dual)"
        return res


def _get(fut, timeout):
    try:
        return fut.result(timeout=timeout)
    except (ASRError, FutureTimeout):
        return None

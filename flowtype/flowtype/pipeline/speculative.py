"""Speculative chunking: for long dictations, transcribe while you're still talking.

While recording, the controller hands us the audio so far every ~300 ms. When there's a natural pause (VAD: at
least `pause_ms` of silence) after at least `min_chunk_s` of audio, everything before the middle of that pause is
sent to ASR in the background. When the key comes up only the remainder is left to transcribe, so a 30-second
dictation pastes about as fast as a 5-second one. If any chunk fails, the caller transcribes the whole recording
the normal way."""

from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from flowtype.asr.base import SAMPLE_RATE, ASRResult
from flowtype.audio.dsp import peak_normalise
from flowtype.guard import hallucination as guard
from flowtype.vad.silero import trim


class SpeculativeSession:
    def __init__(self, asr, vad, prompt: str, lang: str | None, pool: ThreadPoolExecutor, min_chunk_s: float = 4.0,
                 pause_ms: int = 500, tail_ms: int = 300, min_speech_ms: int = 250, target_dbfs: float = -3.0):
        self.asr, self.vad, self.prompt, self.lang, self.pool = asr, vad, prompt, lang, pool
        self.min_chunk = int(min_chunk_s * SAMPLE_RATE)
        self.pause = int(pause_ms * SAMPLE_RATE / 1000)
        self.tail = int(tail_ms * SAMPLE_RATE / 1000)
        self.min_speech_ms, self.target_dbfs = min_speech_ms, target_dbfs
        self.cut = 0
        self.futures: list[Future] = []
        self.retried = False

    @property
    def chunks(self) -> int:
        return len(self.futures)

    def update(self, audio: np.ndarray) -> bool:
        """Look for a pause to cut at; True if a chunk was sent."""
        if len(audio) - self.cut < self.min_chunk + self.tail:
            return False
        region = audio[self.cut : len(audio) - self.tail]
        spans = self.vad.speech_spans(region)
        for (_s1, e1), (s2, _e2) in reversed(list(zip(spans, spans[1:]))):
            if s2 - e1 >= self.pause and e1 >= self.min_chunk:
                at = self.cut + (e1 + s2) // 2
                chunk = audio[self.cut : at].copy()
                self.futures.append(self.pool.submit(self._run, chunk))
                self.cut = at
                return True
        return False

    def _run(self, chunk: np.ndarray) -> ASRResult:
        try:
            t = trim(chunk, self.vad, self.min_speech_ms, 150)
            if t is None:
                return ASRResult(text="")
            clip = peak_normalise(t.audio, self.target_dbfs)
            res = self.asr.transcribe(clip, self.prompt, self.lang)
            if guard.needs_retry(res, self.prompt):
                res = self.asr.transcribe(clip, "", self.lang)
                self.retried = True
            return res
        finally:
            chunk.fill(0)

    def finish(self, audio: np.ndarray, timeout_s: float = 15.0) -> ASRResult:
        """Transcribe the remainder and stitch every chunk together in order. Raises if any chunk failed."""
        rest = self.pool.submit(self._run, audio[self.cut :].copy())
        results = [f.result(timeout=timeout_s) for f in [*self.futures, rest]]
        segs = [s for r in results for s in (r.segments or ([] if not r.text else [_seg(r.text)]))]
        text = " ".join(r.text for r in results if r.text).strip()
        return ASRResult(text=text, segments=segs, model=next((r.model for r in results if r.model), ""), ms=max((r.ms for r in results), default=0))

    def cancel(self) -> None:
        for f in self.futures:
            f.cancel()


def _seg(text):
    from flowtype.asr.base import Segment

    return Segment(text)

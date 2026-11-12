"""Local Whisper (faster-whisper, CTranslate2, int8 on CPU): the fallback when Groq is slow, rate-limited or offline,
and the second opinion in max-accuracy mode. Audio never leaves the machine on this path. The model is downloaded
once (`flowtype fetch-model`) and loaded in the background at startup."""

import threading
import time

import numpy as np

from flowtype.asr.base import ASRError, ASRResult, Segment


class LocalWhisper:
    def __init__(self, model: str = "small", compute_type: str = "int8", beam_size: int = 1, cpu_threads: int = 0):
        self.name = f"local:{model}"
        self._model_name, self._compute, self._beam, self._threads = model, compute_type, beam_size, cpu_threads
        self._model = None
        self._lock = threading.Lock()
        self._error: Exception | None = None

    def load(self) -> None:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(self._model_name, device="cpu", compute_type=self._compute, cpu_threads=self._threads)
                except Exception as exc:
                    self._error = exc
                    raise

    def load_async(self) -> None:
        threading.Thread(target=lambda: _quiet(self.load), daemon=True, name="local-asr-load").start()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult:
        t0 = time.perf_counter()
        try:
            self.load()
            segs, _info = self._model.transcribe(
                audio.astype(np.float32), language=lang, initial_prompt=prompt or None, temperature=0.0,
                beam_size=self._beam, vad_filter=False, condition_on_previous_text=False,
            )
            out = [Segment(s.text.strip(), s.no_speech_prob, s.avg_logprob, s.compression_ratio) for s in segs]
        except Exception as exc:
            raise ASRError(f"local: {type(exc).__name__}: {exc}"[:200]) from exc
        return ASRResult(text=" ".join(s.text for s in out).strip(), segments=out, model=self.name, ms=int((time.perf_counter() - t0) * 1000))


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass

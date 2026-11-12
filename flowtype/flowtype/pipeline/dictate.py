"""One dictation, from captured audio to text at the cursor:

    VAD trim -> peak-normalise -> bias prompt -> ASR (+ one retry without the prompt on a loop/echo)
    -> hallucination guard -> dictionary fixes -> password-field check -> paste -> log latencies

Every stage is timed into a `Dictation` row. The audio buffer is zeroed and dropped when we're done with it."""

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from flowtype.asr.base import ASRError, ASRProvider, ASRResult
from flowtype.asr.prompt import build_bias_prompt
from flowtype.audio.dsp import duration_ms, peak_normalise
from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.dictionary.phonetic import correct
from flowtype.dictionary.terms import polish
from flowtype.guard import hallucination as guard
from flowtype.inject.clipboard import InjectError
from flowtype.store.db import Dictation, Store
from flowtype.vad.silero import VAD, trim


class Injector(Protocol):
    def paste(self, text: str) -> int: ...


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


@dataclass
class Pipeline:
    cfg: Config
    vad: VAD
    asr: ASRProvider
    injector: Injector
    store: Store
    notify: Callable[[str], None] = lambda _msg: None

    def vocabulary(self) -> tuple[list[str], list[str]]:
        """(dictionary most relevant first, starred) from the database plus config."""
        rows = self.store.words()
        words = [r["term"] for r in rows if not r["starred"]] + list(self.cfg.dictionary.words)
        starred = [r["term"] for r in rows if r["starred"]]
        return words, starred

    def transcribe(self, audio: np.ndarray, d: Dictation) -> str | None:
        """Audio in, guarded and corrected text out (None = nothing worth pasting; d.status says why)."""
        c = self.cfg
        d.audio_ms = duration_ms(audio)

        t = time.perf_counter()
        trimmed = trim(audio, self.vad, c.vad.min_speech_ms, c.vad.pad_ms)
        d.vad_ms = _ms(t)
        if trimmed is None:
            d.status = "no_speech"
            return None
        d.speech_ms = trimmed.speech_ms

        t = time.perf_counter()
        clip = peak_normalise(trimmed.audio, c.audio.target_dbfs, c.audio.max_gain_db)
        d.normalise_ms = _ms(t)

        t = time.perf_counter()
        words, starred = self.vocabulary()
        prompt = build_bias_prompt(words, starred, style=c.asr.style)
        d.prompt_ms = _ms(t)

        d.asr_model, d.language = self.asr.name, c.asr.language
        t = time.perf_counter()
        try:
            res: ASRResult = self.asr.transcribe(clip, prompt, c.asr.language)
            d.asr_ms = _ms(t)
            if guard.needs_retry(res, prompt):
                t = time.perf_counter()
                res = self.asr.transcribe(clip, "", c.asr.language)
                d.asr_retry_ms, d.asr_retried = _ms(t), True
        except ASRError as exc:
            d.status, d.error = "error", f"asr: {exc}"
            if d.asr_ms is None:
                d.asr_ms = _ms(t)
            return None
        finally:
            clip.fill(0)
            del clip

        t = time.perf_counter()
        g = guard.clean(res)
        d.guard_ms = _ms(t)
        d.guard_dropped = ",".join(g.dropped) or None
        if not g.text:
            d.status = "empty"
            return None

        t = time.perf_counter()
        text, fixes = correct(g.text, [*starred, *words])
        text = polish(text)
        self.store.bump_uses([f["fixed"] for f in fixes])
        d.dictionary_ms = _ms(t)
        return text

    def run(self, audio: np.ndarray, mode: str, key_up: float, focus: FocusProbe | None = None, postroll_ms: int | None = None) -> Dictation:
        """Process one recording. `key_up` is the time.perf_counter() when the key came up (latency is measured from it)."""
        d = Dictation(mode=mode, postroll_ms=postroll_ms)
        try:
            text = self.transcribe(audio, d)
            if text is not None:
                self._paste(text, d, focus)
        except Exception as exc:  # never let one dictation kill the app
            d.status, d.error = "error", f"{type(exc).__name__}: {exc}"[:300]
        finally:
            audio.fill(0)  # wipe the samples rather than wait for the garbage collector
            del audio
            d.total_ms = _ms(key_up)
            self.store.add_dictation(d, store_text=self.cfg.store.store_text)
        self._report(d)
        return d

    def _paste(self, text: str, d: Dictation, focus: FocusProbe | None) -> None:
        t = time.perf_counter()
        info = focus.result(timeout=0.3) if focus else FocusInfo()
        d.context_ms, d.app = _ms(t), info.app
        if info.is_password and self.cfg.inject.refuse_password_fields:
            d.status = "refused_password"
            return
        out = text + " "  # so the next dictation doesn't run into this one
        t = time.perf_counter()
        try:
            self.injector.paste(out)
        except InjectError as exc:
            d.status, d.error = "error", f"inject: {exc}"
            return
        d.inject_ms = _ms(t)
        d.status, d.text, d.chars, d.words = "pasted", text, len(text), len(text.split())

    def _report(self, d: Dictation) -> None:
        if d.status == "pasted":
            self.notify(f"✓ {d.words} words in {d.total_ms} ms (asr {d.asr_ms} ms{' + retry' if d.asr_retried else ''})")
        elif d.status == "refused_password":
            self.notify("✗ not pasted: the cursor is in a password field")
        elif d.status == "no_speech":
            self.notify("○ no speech heard")
        elif d.status == "empty":
            self.notify(f"○ nothing to paste ({d.guard_dropped or 'empty transcript'})")
        else:
            self.notify(f"✗ {d.error}")

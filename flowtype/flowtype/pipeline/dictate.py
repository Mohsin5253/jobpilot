"""One dictation, from captured audio to text at the cursor:

    context (at key-down) -> VAD trim -> peak-normalise -> bias prompt (style sample, context terms, dictionary)
    -> ASR (speculative chunks, fallback / dual engines; one retry without the prompt on a loop or echo)
    -> hallucination guard -> phonetic dictionary pre-pass -> spoken formatting
    -> LLM clean-up in the app's style (guarded; falls back to the raw text) or command mode
    -> snippets -> password-field check -> paste -> log latencies -> (later) learn from your corrections

Every stage is timed into a `Dictation` row. Audio buffers are zeroed and dropped when we're done with them; text is
stored only with store_text on, and context text never."""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from flowtype.asr.base import ASRError, ASRProvider, ASRResult
from flowtype.asr.prompt import build_bias_prompt
from flowtype.audio.dsp import duration_ms, peak_normalise
from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.context.terms import extract_terms
from flowtype.dictionary.matcher import correct
from flowtype.dictionary.snippets import expand
from flowtype.dictionary.terms import polish
from flowtype.guard import hallucination as guard
from flowtype.guard.llm_guard import strip_fillers
from flowtype.inject.clipboard import InjectError
from flowtype.llm.cleanup import cleanup
from flowtype.llm.styles import detect_style
from flowtype.pipeline.commands import apply_spoken_formatting, run_command
from flowtype.store.db import Dictation, Store
from flowtype.vad.silero import VAD, trim


class Injector(Protocol):
    def paste(self, text: str) -> int: ...


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _timer(delay_s: float, fn: Callable[[], None]) -> None:
    t = threading.Timer(delay_s, fn)
    t.daemon = True
    t.start()


@dataclass
class Pipeline:
    cfg: Config
    vad: VAD
    asr: ASRProvider
    injector: Injector
    store: Store
    notify: Callable[[str], None] = lambda _msg: None
    llm: object | None = None  # a ModelChain / LLMProvider; None = no clean-up or command mode
    probe: Callable[..., FocusInfo] | None = None  # re-reads the field for learning
    schedule: Callable[[float, Callable[[], None]], None] = _timer
    on_state: Callable[[str, str], None] = lambda _state, _msg: None  # the overlay
    last: dict = field(default_factory=dict)

    # --- inputs -------------------------------------------------------------------------------------------------
    def vocabulary(self) -> tuple[list[str], list[str]]:
        """(dictionary most relevant first, starred) from the database plus config."""
        rows = self.store.words()
        words = [r["term"] for r in rows if not r["starred"]] + list(self.cfg.dictionary.words)
        starred = [r["term"] for r in rows if r["starred"]]
        return words, starred

    def build_prompt(self, ctx: FocusInfo | None) -> tuple[str, list[str]]:
        words, starred = self.vocabulary()
        terms = extract_terms(ctx.title, ctx.before_text) if ctx and self.cfg.context.enabled and not ctx.is_password else []
        return build_bias_prompt(words, starred, context_terms=terms, style=self.cfg.asr.style), terms

    # --- stages -------------------------------------------------------------------------------------------------
    def _recognize(self, clip: np.ndarray, prompt: str, d: Dictation) -> ASRResult:
        lang = self.cfg.asr.language
        t = time.perf_counter()
        res = self.asr.transcribe(clip, prompt, lang)
        d.asr_ms = _ms(t)
        if guard.needs_retry(res, prompt):
            t = time.perf_counter()
            res = self.asr.transcribe(clip, "", lang)
            d.asr_retry_ms, d.asr_retried = _ms(t), True
        return res

    def transcribe(self, audio: np.ndarray, d: Dictation, ctx: FocusInfo | None = None, speculative=None) -> tuple[str, list[str]] | None:
        """Audio in, guarded and dictionary-corrected text out, with the terms the LLM may use. None = nothing to
        paste (d.status says why)."""
        c = self.cfg
        d.audio_ms = duration_ms(audio)

        t = time.perf_counter()
        trimmed = trim(audio, self.vad, c.vad.min_speech_ms, c.vad.pad_ms)
        d.vad_ms = _ms(t)
        if trimmed is None:
            d.status = "no_speech"
            if speculative:
                speculative.cancel()
            return None
        d.speech_ms = trimmed.speech_ms

        t = time.perf_counter()
        prompt, ctx_terms = self.build_prompt(ctx)
        d.prompt_ms, d.context_terms = _ms(t), len(ctx_terms)
        d.language, d.asr_mode = c.asr.language, c.asr.mode

        res: ASRResult | None = None
        if speculative is not None and speculative.chunks:
            t = time.perf_counter()
            try:
                res = speculative.finish(audio)
                d.asr_ms, d.chunks, d.asr_retried = _ms(t), speculative.chunks + 1, speculative.retried
            except Exception:
                res = None  # a chunk failed: do it the normal way
        if res is None:
            t = time.perf_counter()
            clip = peak_normalise(trimmed.audio, c.audio.target_dbfs, c.audio.max_gain_db)
            d.normalise_ms = _ms(t)
            t = time.perf_counter()
            try:
                res = self._recognize(clip, prompt, d)
            except ASRError as exc:
                d.status, d.error = "error", f"asr: {exc}"
                d.asr_ms = d.asr_ms if d.asr_ms is not None else _ms(t)  # how long the failure took
                return None
            finally:
                clip.fill(0)
                del clip
        d.asr_model = res.model or self.asr.name

        t = time.perf_counter()
        g = guard.clean(res)
        d.guard_ms = _ms(t)
        d.guard_dropped = ",".join(g.dropped) or None
        if not g.text:
            d.status = "empty"
            return None

        t = time.perf_counter()
        words, starred = self.vocabulary()
        text, fixes = correct(g.text, [*starred, *words])
        text = polish(text)
        self.store.bump_uses([f["fixed"] for f in fixes])
        d.dictionary_ms, d.fixes = _ms(t), len(fixes)
        return text, [*starred, *words, *ctx_terms]

    def compose(self, text: str, known_terms: list[str], ctx: FocusInfo | None, d: Dictation) -> str:
        """Spoken formatting, then the clean-up in the app's style (or verbatim), then snippets."""
        style = detect_style(ctx.app if ctx else None, ctx.title if ctx else None, self.cfg.styles.apps)
        d.style = style.name
        text = apply_spoken_formatting(text)
        # "New paragraph" said first or last is a break before/after the text; the clean-up would trim it away
        body = text.strip("\n")
        lead, trail = text[: len(text) - len(text.lstrip("\n"))], text[len(text.rstrip("\n")):]
        if not body:
            return text
        text = body
        if self.cfg.llm.enabled and self.cfg.llm.mode == "polished" and self.llm is not None:
            r = cleanup(self.llm, text, known_terms, style, timeout_s=self.cfg.llm.budget_ms / 1000)
            text, d.llm_status, d.llm_reason, d.llm_ms, d.llm_model = r.text, r.status, r.reason or None, r.ms or None, r.model or None
        elif style.clean:
            text, d.llm_status = strip_fillers(text), "verbatim"
        snippets = self.store.snippets()
        if snippets:
            text, used = expand(text, snippets)
            d.snippets_used = len(used)
        return lead + text.strip("\n") + trail if text.strip() else text

    # --- the whole dictation ------------------------------------------------------------------------------------
    def run(self, audio: np.ndarray, mode: str, key_up: float, focus: FocusProbe | None = None, postroll_ms: int | None = None,
            *, focus_down: FocusProbe | None = None, speculative=None, command: bool = False) -> Dictation:
        """Process one recording. `key_up` is the time.perf_counter() when the key came up (latency is measured from
        it). `focus_down` is the context read at key-down; `focus` the one read at key-up (used for the safety check)."""
        d = Dictation(mode=mode, postroll_ms=postroll_ms, command=command)
        pasted = None
        try:
            ctx = focus_down.result(timeout=0.1) if focus_down else None
            early = focus.result(timeout=0) if focus is not None and getattr(focus, "done", False) else None
            secret = next((i for i in (ctx, early) if i is not None and i.is_password), None)
            if secret is not None and self.cfg.inject.refuse_password_fields:
                # a password field at key-down (or already known at key-up): the audio never leaves this machine
                d.status, d.app = "refused_password", secret.app
                if speculative is not None:
                    speculative.cancel()
                out = None
            else:
                out = self.transcribe(audio, d, ctx, speculative)
            if out is not None:
                text, known = out
                up = focus.result(timeout=0.3) if focus else FocusInfo()
                if up.is_password and self.cfg.inject.refuse_password_fields:
                    out, text = None, ""  # moved into a password field while it transcribed: no clean-up, no paste
                    d.status, d.app = "refused_password", up.app
                where = up if up.app else (ctx or up)
                if out is None:
                    pass
                elif command:
                    text = self._command(text, ctx, d)
                else:
                    text = self.compose(text, known, where, d)
                if text:
                    pasted = self._paste(text, d, up, command, key_up)
                elif d.status == "pending":
                    d.status = "empty"
        except Exception as exc:  # never let one dictation kill the app
            d.status, d.error = "error", f"{type(exc).__name__}: {exc}"[:300]
        finally:
            audio.fill(0)  # wipe the samples rather than wait for the garbage collector
            del audio
            if d.total_ms is None:
                d.total_ms = _ms(key_up)
            row_id = self.store.add_dictation(d, store_text=self.cfg.store.store_text)
        if pasted and self.cfg.learn.enabled and self.probe is not None:
            app = d.app
            self.schedule(self.cfg.learn.delay_s, lambda: self.learn_from_field(row_id, pasted, app))
        self.last = {"id": row_id, "text": pasted}
        self._report(d)
        return d

    def _command(self, instruction: str, ctx: FocusInfo | None, d: Dictation) -> str:
        if self.llm is None:
            d.status, d.error = "error", "command mode needs the LLM (llm.enabled = true)"
            return ""
        selected = (ctx.selected_text if ctx else "") or ""
        if not selected and hasattr(self.injector, "copy_selection"):
            try:
                selected = self.injector.copy_selection() or ""
            except Exception:
                selected = ""
        t = time.perf_counter()
        r = run_command(self.llm, instruction, selected)
        d.llm_ms, d.llm_status, d.llm_reason, d.style = _ms(t), f"command_{r.status}", r.reason or None, "command"
        if r.status != "ok":
            d.status, d.error = "error", f"command: {r.reason}"
        return r.text

    def _paste(self, text: str, d: Dictation, info: FocusInfo, command: bool, key_up: float | None = None) -> str | None:
        d.context_ms, d.app = info.ms, info.app or d.app
        if info.is_password and self.cfg.inject.refuse_password_fields:
            d.status = "refused_password"
            return None
        # A trailing space so the next dictation doesn't run into this one (not after a newline or in command mode).
        out = text if command or text.endswith("\n") else text + " "
        t = time.perf_counter()
        try:
            sent = self.injector.paste(out)
        except InjectError as exc:
            d.status, d.error = "error", f"inject: {exc}"
            return None
        # The text shows up at the paste keystroke; the clipboard restore after it isn't latency you see
        d.inject_ms = sent if isinstance(sent, int) and sent >= 0 else _ms(t)
        if key_up is not None:
            d.total_ms = int((t - key_up) * 1000) + d.inject_ms
        d.status, d.text, d.chars, d.words = "pasted", text, len(text), len(text.split())
        return out

    def learn_from_field(self, row_id: int, pasted: str, app: str | None) -> None:
        """Re-read the field; record the Edit Rate and learn corrected spellings."""
        from flowtype.dictionary.learn import learn

        try:
            info = self.probe(full=True)
        except Exception:
            return
        if not info.field_text or info.is_password or (app and info.app != app):
            return
        res = learn(pasted, info.field_text)
        if res is None:
            return
        for _wrote, fixed in res.corrections:
            self.store.add_word(fixed, source="learned")
        self.store.update_dictation(row_id, edit_rate=res.edit_rate, learned="; ".join(f"{a} -> {b}" for a, b in res.corrections) or None)
        if res.corrections:
            self.notify("＋ learned " + ", ".join(b for _a, b in res.corrections))

    def _report(self, d: Dictation) -> None:
        if d.status == "pasted":
            extra = f", {d.style}" + (f", clean-up {d.llm_status}" if d.llm_status and d.llm_status != "ok" else "")
            msg = f"✓ {d.words} words in {d.total_ms} ms (asr {d.asr_ms} ms{' + retry' if d.asr_retried else ''}{extra})"
            self.on_state("done", f"{d.words} words · {d.total_ms} ms")
        elif d.status == "refused_password":
            msg = "✗ not pasted: the cursor is in a password field"
            self.on_state("error", "password field: not pasted")
        elif d.status == "no_speech":
            msg = "○ no speech heard"
            self.on_state("idle", "")
        elif d.status == "empty":
            msg = f"○ nothing to paste ({d.guard_dropped or 'empty transcript'})"
            self.on_state("idle", "")
        else:
            msg = f"✗ {d.error}"
            self.on_state("error", (d.error or "error")[:60])
        self.notify(msg)

"""The running app: global hotkey -> controller (state machine + recorder) -> worker (pipeline).

Threads:
- the keyboard hook thread only timestamps key events and queues them;
- the controller runs the push-to-talk state machine, starts/stops the recorder, reads the context at key-down,
  feeds speculative chunks while you talk, and waits out the post-roll;
- one worker runs dictations in order, so pastes never interleave;
- the Qt overlay (when enabled) owns the main thread; otherwise the controller does."""

import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from flowtype.config import Config, data_dir
from flowtype.hotkey.state import Action, PushToTalk, Timing
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store
from flowtype.ui.console import Console

SPECULATIVE_EVERY_S = 0.3


# --- builders -----------------------------------------------------------------------------------------------------
def build_asr(cfg: Config, vocab_fn: Callable[[], list[str]] = lambda: []):
    """The engine the pipeline sees: Groq, wrapped in a local fallback and/or dual mode as configured."""
    from flowtype.secrets import require_key

    if cfg.asr.provider != "groq":
        raise SystemExit(f"ASR provider {cfg.asr.provider!r} isn't supported (use 'groq'; the local model is the fallback)")
    from flowtype.asr.chain import DualASR, FallbackASR
    from flowtype.asr.groq_whisper import GroqWhisper

    key = require_key("groq")
    primary = GroqWhisper(key, cfg.asr.model, cfg.asr.timeout_s, cfg.asr.base_url)
    local = None
    if cfg.asr.fallback == "local" or (cfg.asr.mode == "max_accuracy" and cfg.asr.second_model == "local"):
        from flowtype.asr.local_whisper import LocalWhisper

        local = LocalWhisper(cfg.asr.local_model)
    asr = primary
    if cfg.asr.mode == "max_accuracy":
        second = local if cfg.asr.second_model == "local" else GroqWhisper(key, cfg.asr.second_model, cfg.asr.timeout_s, cfg.asr.base_url)
        asr = DualASR(primary, second, vocab_fn)
    if cfg.asr.fallback == "local" and local is not None:
        asr = FallbackASR(asr, local)
    elif cfg.asr.fallback == "groq":
        fallback_model = "whisper-large-v3" if cfg.asr.model != "whisper-large-v3" else "whisper-large-v3-turbo"
        asr = FallbackASR(asr, GroqWhisper(key, fallback_model, cfg.asr.timeout_s * 1.5, cfg.asr.base_url))
    return asr, primary, local


def build_llm(cfg: Config):
    if not cfg.llm.enabled:
        return None
    from flowtype.llm.groq_llm import GroqLLM, ModelChain
    from flowtype.secrets import require_key

    key = require_key("groq")
    models = [GroqLLM(key, cfg.llm.model, cfg.llm.timeout_s, cfg.llm.base_url, cfg.llm.reasoning)]
    if cfg.llm.fallback_model:
        models.append(GroqLLM(key, cfg.llm.fallback_model, cfg.llm.timeout_s, cfg.llm.base_url, cfg.llm.fallback_reasoning))
    return ModelChain(models)


def build_vad(cfg: Config):
    from flowtype.vad.silero import SileroVAD

    return SileroVAD(threshold=cfg.vad.threshold)


# --- the controller -----------------------------------------------------------------------------------------------
class Controller:
    """Turns key events into recordings and recordings into pipeline jobs. Everything it talks to is injected, so it
    runs in tests without a keyboard, a microphone or Qt."""

    def __init__(self, cfg: Config, recorder, pipeline: Pipeline, probe, submit: Callable, ui=None, post: Callable[[str, str], None] = lambda s, m: None,
                 spec_factory: Callable | None = None, focus_probe_cls=None):
        from flowtype.context.focus import FocusProbe

        self.cfg, self.recorder, self.pipeline, self.probe, self.submit = cfg, recorder, pipeline, probe, submit
        self.ui = ui or Console()
        self.post = post
        self.spec_factory = spec_factory
        self.FocusProbe = focus_probe_cls or FocusProbe
        self.sm = PushToTalk(Timing(cfg.hotkey.tap_max_ms / 1000, cfg.hotkey.double_tap_gap_ms / 1000, cfg.hotkey.max_record_s))
        self.command = False
        self.focus_down = None
        self.spec = None
        self._last_spec = 0.0
        self._started = 0.0

    def handle(self, ev: tuple) -> None:
        kind, at = ev[0], ev[1]
        if kind == "press":
            actions = self.sm.press(at)
            if Action.START in actions:
                self.command = bool(ev[2]) if len(ev) > 2 else False
        elif kind == "release":
            actions = self.sm.release(at)
        elif kind == "other":
            actions = self.sm.other_key(at, ev[2] if len(ev) > 2 else False)
        else:
            actions = self.sm.tick(at)
        for a in actions:
            self._do(a, at)

    def tick(self, now: float) -> None:
        self.handle(("tick", now))
        if self.recorder.recording and self.spec_factory is not None and not self.command and now - self._last_spec >= SPECULATIVE_EVERY_S:
            self._last_spec = now
            ready = self.focus_down is not None and (getattr(self.focus_down, "done", True) or now - self._started >= 1.0)
            if self.spec is None and ready:  # build the prompt once the key-down context is in (or give up after 1 s)
                ctx = self.focus_down.result(timeout=0)
                if ctx.is_password and self.cfg.inject.refuse_password_fields:
                    return  # never stream audio out from a password field
                self.spec = self.spec_factory(ctx)
            if self.spec is not None:
                self.spec.update(self.recorder.peek())

    def _do(self, a: Action, at: float) -> None:
        if a is Action.START:
            self.recorder.start()
            self.focus_down = self.FocusProbe(self.probe)  # context while you speak: terms, selection, style
            self.spec, self._last_spec, self._started = None, at, at
            self.ui.recording()
            self.post("command" if self.command else "recording", "")
        elif a is Action.HANDSFREE_ON:
            self.ui.recording(handsfree=True)
            self.post("handsfree", "")
        elif a is Action.CANCEL:
            if self.recorder.recording:
                self.recorder.cancel()
                if self.spec is not None:
                    self.spec.cancel()
                self.spec = None
                self.ui.cancelled()
                self.post("cancelled", "")
        elif a in (Action.STOP_HOLD, Action.STOP_HANDSFREE):
            focus_up = self.FocusProbe(self.probe)  # runs while we wait for the post-roll and the ASR
            t = time.perf_counter()
            audio = self.recorder.stop()
            postroll_ms = int((time.perf_counter() - t) * 1000)
            mode = "hold" if a is Action.STOP_HOLD else "handsfree"
            self.ui.status("… transcribing")
            self.post("transcribing", "")
            self.submit(self.pipeline.run, audio, mode, at, focus_up, postroll_ms, focus_down=self.focus_down, speculative=self.spec, command=self.command)
            self.spec, self.focus_down, self.command = None, None, False


# --- run ----------------------------------------------------------------------------------------------------------
def run(cfg: Config) -> None:
    from flowtype.audio.recorder import Recorder
    from flowtype.context import focus
    from flowtype.hotkey.listener import HotkeyListener
    from flowtype.inject.clipboard import ClipboardInjector, default_backend, make_send_paste
    from flowtype.pipeline.speculative import SpeculativeSession
    from flowtype.ui import overlay as ov

    ui = Console()
    ui.status("starting…")
    store = Store(data_dir() / "flowtype.db")
    if cfg.store.store_text and cfg.store.history_days > 0:
        store.purge_text(cfg.store.history_days)
    def vocab() -> list[str]:
        return [r["term"] for r in store.words()] + list(cfg.dictionary.words)

    asr, primary, local = build_asr(cfg, vocab)
    llm = build_llm(cfg)
    vad = build_vad(cfg)
    focus.warm()
    from flowtype.asr.prompt import count_tokens

    count_tokens("")  # load Whisper's tokenizer now, not on the first dictation
    injecting = threading.Event()
    injector = ClipboardInjector(default_backend(), make_send_paste("v"), cfg.inject.restore_delay_ms, injecting, send_copy=make_send_paste("c"))
    use_overlay = cfg.ui.overlay and ov.available()
    if cfg.ui.overlay and not use_overlay:
        ui.status(f"⚠ no overlay ({ov.unavailable_reason}); status shows here instead")
    bus = ov.OverlayBus()
    probe = focus.platform_probe()
    pipeline = Pipeline(cfg, vad, asr, injector, store, notify=ui.status, llm=llm, probe=probe, on_state=bus.post if use_overlay else (lambda s, m: None))
    recorder = Recorder(cfg.audio.preroll_ms, cfg.audio.postroll_ms, cfg.audio.device or None)
    recorder.open()
    threading.Thread(target=primary.warm, daemon=True).start()
    if llm is not None:
        threading.Thread(target=lambda: [m.warm() for m in llm.models], daemon=True).start()
    if local is not None:
        local.load_async()

    events: queue.Queue = queue.Queue()
    listener = HotkeyListener(cfg.hotkey.key, events, injecting, cfg.command.modifier)
    listener.start()
    if not listener.trusted:
        ui.status("⚠ macOS hasn't allowed this app to read the keyboard: grant Input Monitoring and Accessibility (see README)")
    problem = focus.detection_problem() if cfg.inject.refuse_password_fields else None
    if problem:
        ui.status(f"⚠ password-field detection isn't working, so it can't refuse to paste into one ({problem})")

    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dictation")
    spec_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="speculative")

    def spec_factory(ctx):
        prompt, _terms = pipeline.build_prompt(ctx)
        return SpeculativeSession(asr, vad, prompt, cfg.asr.language, spec_pool, cfg.asr.chunk_min_s, cfg.asr.chunk_pause_ms,
                                  min_speech_ms=cfg.vad.min_speech_ms, target_dbfs=cfg.audio.target_dbfs)

    ctl = Controller(cfg, recorder, pipeline, probe, worker.submit, ui, bus.post if use_overlay else (lambda s, m: None),
                     spec_factory if cfg.asr.speculative else None)
    mod = f"; {cfg.command.modifier.capitalize()}+{cfg.hotkey.key} for a command" if cfg.command.modifier != "none" and llm else ""
    ui.status(f"ready: hold {cfg.hotkey.key} and speak (double-tap for hands-free{mod}). Ctrl+C to quit. Data: {data_dir()}")
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                ev = events.get(timeout=0.03)
            except queue.Empty:
                ctl.tick(time.perf_counter())
            else:
                ctl.handle(ev)
        stop.set()

    try:
        if use_overlay:
            ov.run_overlay(bus, lambda: recorder.level, stop, loop)
        else:
            loop()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        ui.status("bye")
        listener.stop()
        recorder.close()
        worker.shutdown(wait=True)
        spec_pool.shutdown(wait=False, cancel_futures=True)
        store.close()
        sys.stdout.flush()

"""The running app: global hotkey -> controller thread (state machine + recorder) -> worker thread (pipeline).

Threads:
- the keyboard hook thread only timestamps key events and queues them;
- the controller (main thread) runs the push-to-talk state machine, starts/stops the recorder and waits out the
  post-roll;
- one worker runs dictations in order, so pastes never interleave."""

import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flowtype.config import Config, data_dir
from flowtype.hotkey.state import Action, PushToTalk, Timing
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store
from flowtype.ui.console import Console


def build_asr(cfg: Config):
    from flowtype.secrets import require_key

    if cfg.asr.provider != "groq":
        raise SystemExit(f"ASR provider {cfg.asr.provider!r} isn't available in Phase 1 (only 'groq')")
    from flowtype.asr.groq_whisper import GroqWhisper

    return GroqWhisper(require_key("groq"), cfg.asr.model, cfg.asr.timeout_s, cfg.asr.base_url)


def build_vad(cfg: Config):
    from flowtype.vad.silero import SileroVAD

    return SileroVAD(threshold=cfg.vad.threshold)


def run(cfg: Config) -> None:
    from flowtype.audio.recorder import Recorder
    from flowtype.context import focus
    from flowtype.hotkey.listener import HotkeyListener
    from flowtype.inject.clipboard import ClipboardInjector, default_backend, make_send_paste

    ui = Console()
    ui.status("starting…")
    store = Store(data_dir() / "flowtype.db")
    asr = build_asr(cfg)
    vad = build_vad(cfg)
    focus.warm()
    from flowtype.asr.prompt import count_tokens

    count_tokens("")  # load Whisper's tokenizer now, not on the first dictation
    injecting = threading.Event()
    injector = ClipboardInjector(default_backend(), make_send_paste(), cfg.inject.restore_delay_ms, injecting)
    pipeline = Pipeline(cfg, vad, asr, injector, store, notify=ui.status)
    recorder = Recorder(cfg.audio.preroll_ms, cfg.audio.postroll_ms, cfg.audio.device or None)
    recorder.open()
    threading.Thread(target=asr.warm, daemon=True).start()

    events: queue.Queue = queue.Queue()
    listener = HotkeyListener(cfg.hotkey.key, events, injecting)
    listener.start()
    if not listener.trusted:
        ui.status("⚠ macOS hasn't allowed this app to read the keyboard: grant Input Monitoring and Accessibility (see README)")
    sm = PushToTalk(Timing(cfg.hotkey.tap_max_ms / 1000, cfg.hotkey.double_tap_gap_ms / 1000, cfg.hotkey.max_record_s))
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dictation")
    probe = focus.platform_probe()
    if cfg.inject.refuse_password_fields and probe().is_password is None:
        ui.status(f"⚠ password-field detection isn't working, so it can't refuse to paste into one ({focus.last_error or 'unsupported OS'})")
    ui.status(f"ready: hold {cfg.hotkey.key} and speak (double-tap for hands-free). Ctrl+C to quit. Data: {data_dir()}")

    try:
        while True:
            try:
                ev = events.get(timeout=0.03)
            except queue.Empty:
                ev, actions = ("tick", time.perf_counter()), sm.tick(time.perf_counter())
            else:
                kind, at = ev[0], ev[1]
                actions = sm.press(at) if kind == "press" else sm.release(at) if kind == "release" else sm.other_key(at, ev[2])
            for a in actions:
                if a is Action.START:
                    recorder.start()
                    ui.recording()
                elif a is Action.HANDSFREE_ON:
                    ui.recording(handsfree=True)
                elif a is Action.CANCEL:
                    if recorder.recording:
                        recorder.cancel()
                        ui.cancelled()
                elif a in (Action.STOP_HOLD, Action.STOP_HANDSFREE):
                    key_up = ev[1]
                    probe_job = focus.FocusProbe(probe)  # runs while we wait for the post-roll and the ASR
                    t = time.perf_counter()
                    audio = recorder.stop()
                    postroll_ms = int((time.perf_counter() - t) * 1000)
                    mode = "hold" if a is Action.STOP_HOLD else "handsfree"
                    ui.status("… transcribing")
                    worker.submit(pipeline.run, audio, mode, key_up, probe_job, postroll_ms)
    except KeyboardInterrupt:
        ui.status("bye")
    finally:
        listener.stop()
        recorder.close()
        worker.shutdown(wait=True)
        store.close()
        sys.stdout.flush()

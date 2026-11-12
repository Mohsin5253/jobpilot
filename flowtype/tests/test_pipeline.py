import time

import numpy as np

from flowtype.asr.base import ASRError, ASRResult, Segment
from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import STAGES, Store

SR = 16000


class SpeechAt:
    """A VAD that reports speech wherever the signal is loud."""

    def speech_spans(self, audio):
        idx = np.flatnonzero(np.abs(audio) > 0.05)
        return [(int(idx[0]), int(idx[-1]) + 1)] if idx.size else []


class FakeASR:
    name = "fake-whisper"

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def transcribe(self, audio, prompt, lang):
        self.calls.append({"prompt": prompt, "lang": lang, "peak": float(np.max(np.abs(audio))), "n": len(audio)})
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeInjector:
    def __init__(self):
        self.pasted = []

    def paste(self, text):
        self.pasted.append(text)
        return 3


def speech_audio(seconds=1.0, lead=0.5):
    a = np.zeros(int((lead + seconds + 0.5) * SR), np.float32)
    a[int(lead * SR) : int((lead + seconds) * SR)] = 0.2 * np.sin(np.linspace(0, 2000, int(seconds * SR)))
    return a


def make(asr, cfg=None, store=None):
    store = store or Store(":memory:")
    inj = FakeInjector()
    return Pipeline(cfg or Config(), SpeechAt(), asr, inj, store), inj, store


def ok(text):
    return ASRResult(text=text, segments=[Segment(text, no_speech_prob=0.01, avg_logprob=-0.2)])


def test_happy_path_pastes_and_logs_latencies():
    asr = FakeASR(ok("Send the jit hub link to Mohsin."))
    pipe, inj, store = make(asr)
    pipe.store.add_word("Mohsin")
    audio = speech_audio()
    d = pipe.run(audio, "hold", time.perf_counter(), FocusProbe(lambda: FocusInfo(app="notepad.exe", is_password=False)), postroll_ms=251)
    assert d.status == "pasted"
    assert inj.pasted == ["Send the GitHub link to Mohsin. "]
    assert asr.calls[0]["lang"] == "en" and "Mohsin" in asr.calls[0]["prompt"]
    assert abs(asr.calls[0]["peak"] - 10 ** (-3 / 20)) < 0.01  # normalised to -3 dBFS
    assert asr.calls[0]["n"] < len(audio)  # silence trimmed
    row = store.recent(1)[0]
    assert row["status"] == "pasted" and row["app"] == "notepad.exe" and row["postroll_ms"] == 251
    for stage in ("vad_ms", "normalise_ms", "prompt_ms", "asr_ms", "guard_ms", "dictionary_ms", "context_ms", "inject_ms", "total_ms"):
        assert row[stage] is not None, stage
    assert row["text"] is None  # text isn't stored unless store_text is on
    assert not audio.any()  # the buffer was wiped


def test_text_stored_only_when_opted_in():
    cfg = Config()
    cfg.store.store_text = True
    pipe, _, store = make(FakeASR(ok("Hello there.")), cfg)
    pipe.run(speech_audio(), "hold", time.perf_counter())
    assert store.recent(1)[0]["text"] == "Hello there."


def test_silence_pastes_nothing_and_skips_asr():
    asr = FakeASR()
    pipe, inj, store = make(asr)
    d = pipe.run(np.zeros(SR, np.float32), "hold", time.perf_counter())
    assert d.status == "no_speech" and inj.pasted == [] and asr.calls == []
    assert store.recent(1)[0]["status"] == "no_speech"


def test_phantom_pastes_nothing():
    pipe, inj, _ = make(FakeASR(ASRResult(text="Thanks for watching!", segments=[Segment("Thanks for watching!")])))
    d = pipe.run(speech_audio(), "hold", time.perf_counter())
    assert d.status == "empty" and inj.pasted == []


def test_loop_retries_once_without_prompt():
    loop = ASRResult(text="okay okay okay okay okay", segments=[Segment("okay okay okay okay okay", compression_ratio=2.8)])
    asr = FakeASR(loop, ok("Okay, let's ship it."))
    pipe, inj, store = make(asr)
    pipe.store.add_word("Flowtype")
    d = pipe.run(speech_audio(), "hold", time.perf_counter())
    assert [c["prompt"] != "" for c in asr.calls] == [True, False]
    assert d.asr_retried and inj.pasted == ["Okay, let's ship it. "]
    assert store.recent(1)[0]["asr_retry_ms"] is not None


def test_password_field_is_refused():
    pipe, inj, store = make(FakeASR(ok("hunter2")))
    d = pipe.run(speech_audio(), "hold", time.perf_counter(), FocusProbe(lambda: FocusInfo(app="chrome.exe", is_password=True)))
    assert d.status == "refused_password" and inj.pasted == []
    assert store.recent(1)[0]["text"] is None


def test_asr_failure_is_logged_not_raised():
    pipe, inj, store = make(FakeASR(ASRError("ReadTimeout")))
    d = pipe.run(speech_audio(), "hold", time.perf_counter())
    assert d.status == "error" and "ReadTimeout" in d.error and inj.pasted == []
    assert store.recent(1)[0]["asr_ms"] is not None


def test_phonetic_dictionary_fix():
    pipe, inj, _ = make(FakeASR(ok("Ask Mohasin Sidpurwala about it.")))
    pipe.store.add_word("Mohsin Sidhpurwala", starred=True)
    pipe.run(speech_audio(), "hold", time.perf_counter())
    assert inj.pasted == ["Ask Mohsin Sidhpurwala about it. "]


def test_latency_summary():
    store = Store(":memory:")
    for _ in range(3):
        make(FakeASR(ok("Hi.")), store=store)[0].run(speech_audio(), "hold", time.perf_counter())
    s = store.latency_summary()
    assert set(s) <= set(STAGES) and s["total_ms"]["n"] == 3

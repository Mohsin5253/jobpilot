import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fakes import SR, FakeASR, FakeInjector, SpeechAt, ok

from flowtype.asr.base import ASRError, ASRResult, Segment
from flowtype.asr.chain import DualASR, FallbackASR, confidence, pick
from flowtype.config import Config
from flowtype.pipeline.dictate import Pipeline
from flowtype.pipeline.speculative import SpeculativeSession
from flowtype.store.db import Store

A = np.ones(SR, np.float32) * 0.1


def test_fallback_on_error_and_circuit_breaker():
    now = [0.0]
    primary = FakeASR(ASRError("ConnectTimeout"), name="groq")
    local = FakeASR(ok("hello", model="local:small"), name="local:small")
    chain = FallbackASR(primary, local, breaker_s=60, clock=lambda: now[0])
    assert chain.transcribe(A, "", "en").model == "local:small"
    assert chain.transcribe(A, "", "en").model == "local:small"
    assert len(primary.calls) == 1  # skipped while the breaker is open
    now[0] = 61
    primary.results = [ok("back online", model="groq")]
    assert chain.transcribe(A, "", "en").text == "back online"


def seg(text, lp):
    return ASRResult(text=text, segments=[Segment(text, avg_logprob=lp)], model=text)


def test_pick_prefers_confident_and_dictionary_hits():
    assert pick(seg("send it to kavia", -0.9), seg("send it to Kavya", -0.3)).text == "send it to Kavya"
    assert pick(seg("send it to Kavya", -0.5), seg("send it to Kavia", -0.45), ["Kavya"]).text == "send it to Kavya"
    a, b = seg("the same words here", -0.9), seg("the same words here", -0.1)
    assert pick(a, b) is a  # agreement keeps the primary
    assert pick(None, b) is b
    assert confidence(ASRResult(text="")) < -5


def test_dual_runs_both_and_survives_one_failing():
    dual = DualASR(FakeASR(ASRError("x"), name="a"), FakeASR(seg("only b", -0.2), name="b"))
    assert dual.transcribe(A, "", "en").text == "only b"


def test_dual_does_not_wait_long_for_a_slow_engine():
    class Slow:
        name = "slow"

        def transcribe(self, *a):
            time.sleep(1.0)
            return seg("slow", -0.1)

    dual = DualASR(FakeASR(seg("fast one", -0.3), name="fast"), Slow(), extra_wait_s=0.1)
    t = time.perf_counter()
    assert dual.transcribe(A, "", "en").text == "fast one" and time.perf_counter() - t < 0.5


def speech_with_pauses(parts_s=(2.5, 2.5, 1.0), pause_s=0.8):
    chunks = []
    for p in parts_s:
        chunks.append(0.2 * np.sin(np.linspace(0, 300 * p, int(p * SR))).astype(np.float32))
        chunks.append(np.zeros(int(pause_s * SR), np.float32))
    return np.concatenate(chunks)


class ByLength:
    """Answers by clip length, so the result doesn't depend on which thread runs first."""

    name = "by-length"

    def __init__(self):
        self.prompts = []

    def transcribe(self, audio, prompt, lang):
        self.prompts.append(prompt)
        return ok("long part." if len(audio) > 4 * SR else "short part.")


def test_speculative_sends_chunks_at_pauses_and_stitches_in_order():
    audio = speech_with_pauses((4.5, 1.0, 1.0))
    asr = ByLength()
    s = SpeculativeSession(asr, SpeechAt(), "prompt", "en", ThreadPoolExecutor(2), min_chunk_s=4.0, pause_ms=500)
    sent = [s.update(audio[: int(t * SR)]) for t in np.arange(0.3, len(audio) / SR, 0.3)]
    assert sum(sent) == 1 and s.chunks == 1
    assert s.finish(audio).text == "long part. short part."
    assert asr.prompts == ["prompt", "prompt"]


def test_speculative_waits_for_enough_audio():
    s = SpeculativeSession(ByLength(), SpeechAt(), "", "en", ThreadPoolExecutor(1), min_chunk_s=4.0)
    assert not s.update(speech_with_pauses((1.0, 1.0)))


def test_pipeline_uses_speculative_chunks():
    audio = speech_with_pauses((2.5, 2.5, 2.5, 1.0))
    asr = FakeASR(ok("one."), ok("two."), ok("three."))
    pool = ThreadPoolExecutor(2)
    s = SpeculativeSession(asr, SpeechAt(), "p", "en", pool)
    for t in np.arange(0.3, len(audio) / SR, 0.3):
        s.update(audio[: int(t * SR)])
    inj = FakeInjector()
    d = Pipeline(Config(), SpeechAt(), FakeASR(ok("should not be used")), inj, Store(":memory:")).run(audio.copy(), "hold", time.perf_counter(), speculative=s)
    assert d.chunks == s.chunks + 1 >= 2
    assert "should not be used" not in inj.pasted[0]


def test_pipeline_falls_back_to_whole_audio_when_a_chunk_fails():
    audio = speech_with_pauses((2.5, 2.5, 1.0))
    pool = ThreadPoolExecutor(2)
    s = SpeculativeSession(FakeASR(ASRError("boom")), SpeechAt(), "p", "en", pool)
    for t in np.arange(0.3, len(audio) / SR, 0.3):
        s.update(audio[: int(t * SR)])
    inj = FakeInjector()
    Pipeline(Config(), SpeechAt(), FakeASR(ok("whole thing.")), inj, Store(":memory:")).run(audio.copy(), "hold", time.perf_counter(), speculative=s)
    assert inj.pasted == ["Whole thing. "]

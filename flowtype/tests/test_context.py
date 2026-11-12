import time

from fakes import FakeASR, FakeInjector, SpeechAt, ok, speech_audio

from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.context.terms import extract_terms
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store


def test_extracts_names_identifiers_and_acronyms():
    before = "Deploy notes. We moved the Zeta cluster to Kubernetes and renamed getUserById in user_service. The SLA is fine."
    terms = extract_terms("Deploy notes - Notepad", before)
    for t in ("Zeta", "Kubernetes", "getUserById", "user_service", "SLA"):
        assert t in terms
    assert "We" not in terms and "The" not in terms and "Deploy" not in terms  # sentence starts aren't names


def test_nearest_terms_come_last_and_title_chrome_is_dropped():
    terms = extract_terms("Quarterly Plan - Google Chrome", "then Asha said that Vikram agreed")
    assert terms[-1] == "Vikram"
    assert "Chrome" not in terms and "Google" not in terms


def test_limit():
    assert len(extract_terms("", " ".join(f"and Name{i}x" for i in range(100)), limit=20)) == 20


def test_context_terms_reach_the_bias_prompt_but_not_from_password_fields():
    asr = FakeASR(ok("Scale the zeta cluster."))
    pipe = Pipeline(Config(), SpeechAt(), asr, FakeInjector(), Store(":memory:"))
    down = FocusProbe(lambda: FocusInfo(app="Code.exe", title="infra.md - Visual Studio Code", before_text="we run the Zeta cluster on Kubernetes", is_password=False))
    d = pipe.run(speech_audio(), "hold", time.perf_counter(), focus_down=down)
    assert "Zeta" in asr.calls[0]["prompt"] and "Kubernetes" in asr.calls[0]["prompt"] and d.context_terms >= 2

    asr2 = FakeASR(ok("hi"))
    pw = FocusProbe(lambda: FocusInfo(app="x", before_text="SecretName Hunter2", is_password=True))
    Pipeline(Config(), SpeechAt(), asr2, FakeInjector(), Store(":memory:")).run(speech_audio(), "hold", time.perf_counter(), focus_down=pw)
    assert asr2.calls == []  # a password field at key-down: nothing is transcribed at all


def test_context_can_be_turned_off():
    cfg = Config()
    cfg.context.enabled = False
    asr = FakeASR(ok("x y z"))
    down = FocusProbe(lambda: FocusInfo(before_text="the Zeta cluster"))
    Pipeline(cfg, SpeechAt(), asr, FakeInjector(), Store(":memory:")).run(speech_audio(), "hold", time.perf_counter(), focus_down=down)
    assert "Zeta" not in asr.calls[0]["prompt"]

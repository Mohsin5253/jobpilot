import time

import pytest
from fakes import FakeASR, FakeInjector, FakeLLM, SpeechAt, ok, speech_audio

from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.guard.llm_guard import check, spoken_numbers, strip_fillers
from flowtype.llm.base import LLMError, RateLimited
from flowtype.llm.cleanup import EXAMPLE_TERMS, FEW_SHOTS, SYSTEM, cleanup, messages, request_tokens
from flowtype.llm.groq_llm import ModelChain
from flowtype.llm.styles import STYLES, detect_style
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store

GENERAL = STYLES["general"]


# --- guardrails ---------------------------------------------------------------------------------------------------
def test_accepts_a_faithful_cleanup():
    raw = "um so I I built the the API in flask no wait FastAPI and it handled like two hundred requests"
    assert check(raw, "I built the API in FastAPI, and it handled 200 requests.", []).ok


def test_accepts_a_list():
    raw = "three things first fix the login bug second update the docs and third tag the build"
    assert check(raw, "Three things:\n1. Fix the login bug.\n2. Update the docs.\n3. Tag the build.", []).ok


@pytest.mark.parametrize("out,reason", [
    ("Sure, here's a polished version: Can you send the report?", "reply"),
    ("Can you send the report to Rahul by Friday?", "added 'Rahul'"),
    ("Can you send the 3 reports by Friday?", "number 3"),
    ("Yes.", "length"),
    ("Could you please forward the quarterly financial summary document to everyone on the team before Friday evening ends?", "length"),
])
def test_rejects_unfaithful_rewrites(out, reason):
    v = check("can you send the report by friday", out, [])
    assert not v.ok and (reason.split()[-1] in v.reason or reason in v.reason), v.reason


def test_times_written_as_digits_are_fine():
    assert check("lets meet on monday at ten", "Let's meet on Monday at 10:00.", []).ok
    assert check("call me at four thirty", "Call me at 4:30.", []).ok
    assert not check("call me at four", "Call me at 4:45.", []).ok


def test_sound_alike_spelling_fixes_are_allowed_without_a_dictionary():
    # Live case: Whisper heard "fast RP"; the LLM wrote FastAPI. Invented names stay rejected.
    assert check("The fast RP endpoint returns in forty milliseconds", "The FastAPI endpoint returns in 40 milliseconds.", []).ok
    assert check("we moved the billing service to cooper nets", "We moved the billing service to Kubernetes.", []).ok
    assert not check("can you send the report by friday", "Can you send the report to Rahul by Friday?", []).ok
    assert not check("we moved the billing service to the cloud", "We moved the billing service to Kotlin.", []).ok


def test_known_terms_may_be_added():
    assert check("send it to kavia", "Send it to Kavya.", ["Kavya"]).ok


def test_spoken_numbers():
    assert {"200", "1.5", "500000"} <= spoken_numbers("two hundred, one point five and five lakh")


def test_strip_fillers():
    assert strip_fillers("um so I I think uh yes") == "So I think yes"


# --- prompt -------------------------------------------------------------------------------------------------------
def test_few_shots_use_only_fictional_names():
    blob = SYSTEM + EXAMPLE_TERMS + " ".join(a + b for a, b in FEW_SHOTS)
    for real in ("Mohsin", "Sidhpurwala", "Rizvi", "Mohasin"):
        assert real not in blob


def test_request_stays_under_1000_tokens():
    assert request_tokens(messages("short one", ["Kavya"], GENERAL)) <= 1000
    long = " ".join(["we discussed the roadmap and the hiring plan for the quarter"] * 40)
    msgs = messages(long, [f"Term{i}" for i in range(60)], GENERAL)
    assert request_tokens(msgs) <= 1000 or len(msgs) == 2  # examples dropped first


# --- the call -----------------------------------------------------------------------------------------------------
def test_cleanup_ok():
    r = cleanup(FakeLLM("Hey Kavya, can we move the call to 4:30?"), "hey kavya can we uh move the call to four thirty", ["Kavya"], GENERAL)
    assert r.status == "ok" and r.text == "Hey Kavya, can we move the call to 4:30?"


def test_rejected_rewrite_falls_back_to_filler_stripped_text():
    r = cleanup(FakeLLM("Sure! Here's the message: Can we move the call?"), "um can we move the call to four thirty", [], GENERAL)
    assert r.status == "rejected" and r.text == "Can we move the call to four thirty"


def test_llm_error_falls_back():
    r = cleanup(FakeLLM(LLMError("ReadTimeout")), "uh please send the deck tonight", [], GENERAL)
    assert r.status == "error" and r.text == "Please send the deck tonight"


def test_terminal_style_keeps_exact_words():
    llm = FakeLLM("should not be called")
    r = cleanup(llm, "git commit dash m fix typo", [], STYLES["terminal"])
    assert r.status == "skipped" and r.text == "git commit dash m fix typo" and llm.calls == []


def test_empty_output_for_pure_filler():
    assert cleanup(FakeLLM("(empty)"), "um uh yeah", [], GENERAL).text == ""


def test_model_chain_skips_a_rate_limited_model():
    class M:
        def __init__(self, name, out):
            self.name, self.out, self.n = name, out, 0

        def chat(self, *a, **k):
            self.n += 1
            if isinstance(self.out, Exception):
                raise self.out
            return self.out

    a, b = M("qwen", RateLimited(30)), M("gpt-oss", "fine")
    chain = ModelChain([a, b])
    assert chain.chat_with_model([]) == ("fine", "gpt-oss")
    assert chain.chat_with_model([]) == ("fine", "gpt-oss")
    assert a.n == 1  # cooling down: not asked again


# --- styles -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("app,title,style", [
    ("OUTLOOK.EXE", "Inbox - Outlook", "email"), ("slack.exe", "", "chat"), ("WhatsApp", "", "chat"),
    ("Code.exe", "main.py - flowtype", "code"), ("WindowsTerminal.exe", "", "terminal"), ("iTerm2", "", "terminal"),
    ("notepad.exe", "Untitled - Notepad", "document"), ("chrome.exe", "Inbox (3) - Gmail - Google Chrome", "email"),
    ("chrome.exe", "Pull request #12 · GitHub - Google Chrome", "code"), ("chrome.exe", "Weather", "general"), (None, None, "general"),
])
def test_detect_style(app, title, style):
    assert detect_style(app, title).name == style


def test_style_override():
    assert detect_style("chrome.exe", "Jira", {"jira": "document"}).name == "document"


# --- in the pipeline ----------------------------------------------------------------------------------------------
def test_pipeline_cleans_up_in_the_apps_style():
    llm = FakeLLM("Hey Kavya, can we move the call to 4:30?")
    inj = FakeInjector()
    pipe = Pipeline(Config(), SpeechAt(), FakeASR(ok("hey kavya can we uh move the call to four thirty")), inj, Store(":memory:"), llm=llm)
    d = pipe.run(speech_audio(), "hold", time.perf_counter(), FocusProbe(lambda: FocusInfo(app="slack.exe", is_password=False)))
    assert inj.pasted == ["Hey Kavya, can we move the call to 4:30? "]
    assert d.style == "chat" and d.llm_status == "ok"
    assert "chat message" in llm.calls[0][0]["content"]


def test_verbatim_mode_skips_the_llm():
    cfg = Config()
    cfg.llm.mode = "verbatim"
    llm, inj = FakeLLM("x"), FakeInjector()
    Pipeline(cfg, SpeechAt(), FakeASR(ok("um send it now")), inj, Store(":memory:"), llm=llm).run(speech_audio(), "hold", time.perf_counter())
    assert inj.pasted == ["Send it now "] and llm.calls == []

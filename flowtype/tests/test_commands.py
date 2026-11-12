import time

from fakes import FakeASR, FakeInjector, FakeLLM, SpeechAt, ok, speech_audio

from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.llm.base import LLMError
from flowtype.pipeline.commands import apply_spoken_formatting, run_command
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store


def test_spoken_formatting():
    assert apply_spoken_formatting("Dear team, new paragraph thanks for coming. new line Kavya") == "Dear team\n\nThanks for coming\nKavya"


def test_command_rewrites_selection_and_strips_preface():
    llm = FakeLLM("Sure, here's the formal version:\nCould you please send the report?")
    r = run_command(llm, "make this more formal", "send the report pls")
    assert r.status == "ok" and r.text == "Could you please send the report?"
    assert "SELECTED TEXT:\nsend the report pls" in llm.calls[0][1]["content"]


def test_command_failures():
    assert run_command(FakeLLM(LLMError("x")), "shorten", "text").status == "error"
    assert run_command(FakeLLM(""), "shorten", "text").status == "empty"
    assert run_command(FakeLLM("word " * 500), "expand", "two words").status == "rejected"


def test_pipeline_command_mode_uses_the_selection():
    llm = FakeLLM("Could you please send the report?")
    inj = FakeInjector()
    pipe = Pipeline(Config(), SpeechAt(), FakeASR(ok("make this more formal")), inj, Store(":memory:"), llm=llm)
    down = FocusProbe(lambda: FocusInfo(app="OUTLOOK.EXE", selected_text="send the report pls"))
    d = pipe.run(speech_audio(), "hold", time.perf_counter(), focus_down=down, command=True)
    assert inj.pasted == ["Could you please send the report?"] and d.command and d.llm_status == "command_ok"


def test_pipeline_command_mode_copies_the_selection_when_uia_cannot_read_it():
    llm = FakeLLM("Bonjour")
    inj = FakeInjector(selection="Hello")
    Pipeline(Config(), SpeechAt(), FakeASR(ok("translate to French")), inj, Store(":memory:"), llm=llm).run(speech_audio(), "hold", time.perf_counter(), command=True)
    assert "SELECTED TEXT:\nHello" in llm.calls[0][1]["content"] and inj.pasted == ["Bonjour"]

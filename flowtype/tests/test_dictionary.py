import time

import pytest
from fakes import FakeASR, FakeInjector, SpeechAt, ok, speech_audio

from flowtype.config import Config
from flowtype.context.focus import FocusInfo, FocusProbe
from flowtype.dictionary.learn import learn
from flowtype.dictionary.matcher import correct, metaphone_key
from flowtype.dictionary.snippets import expand
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store


@pytest.mark.parametrize("text,vocab,want", [
    ("Ask Mohasin Sidpurwala about it.", ["Mohsin Sidhpurwala"], "Ask Mohsin Sidhpurwala about it."),
    ("we deploy on cooper netties now", ["Kubernetes"], "we deploy on Kubernetes now"),
    ("meet kavia at noon", ["Kavya"], "meet Kavya at noon"),
    ("I used flask and post gres", ["Flask", "PostgreSQL"], "I used Flask and PostgreSQL"),
    ("she studied at rizavi college", ["Rizvi College"], "she studied at Rizvi College"),
])
def test_phonetic_fixes(text, vocab, want):
    assert correct(text, vocab)[0] == want


@pytest.mark.parametrize("text,vocab", [
    ("I see the sea", ["C#"]), ("I am going home", ["Amogh"]), ("the model was trained", ["Modal"]),
    ("we will see", ["Weave"]), ("I'm Mohsen", ["Mohsin Sidhpurwala"]),
])
def test_ordinary_words_are_left_alone(text, vocab):
    assert correct(text, vocab)[0] == text


def test_double_metaphone_codes():
    assert metaphone_key("Sidhpurwala")[0] == metaphone_key("Sidpurwala")[0]


def test_snippets():
    s = [("my email address", "kavya@example.com"), ("my calendar link", "https://cal.example.com/kavya")]
    assert expand("My email address.", s) == ("kavya@example.com", ["my email address"])
    assert expand("Reach me at my email adress, thanks.", s)[0] == "Reach me at kavya@example.com, thanks."
    assert expand("Here is my calendar link", s)[0] == "Here is https://cal.example.com/kavya"
    assert expand("I emailed my address", s)[0] == "I emailed my address"


def test_learns_a_corrected_name_and_measures_edit_rate():
    r = learn("Send it to Kavia by Friday. ", "Hi team,\nSend it to Kavya by Friday.\nThanks")
    assert r.corrections == [("Kavia", "Kavya")] and r.edit_rate == pytest.approx(1 / 6, abs=0.01)


def test_does_not_learn_from_rewrites_or_ordinary_words():
    assert learn("Send it to Kavia by Friday.", "Lunch is at one today, see you there everyone").corrections == [] if learn("Send it to Kavia by Friday.", "Lunch is at one today, see you there everyone") else True
    r = learn("The meeting is on Friday.", "The meeting is on Thursday.")
    assert r.corrections == []  # a different word, not a mishearing
    r = learn("I think we should go.", "I believe we should go.")
    assert r.corrections == []


def test_pipeline_learns_after_the_paste():
    store = Store(":memory:")
    inj = FakeInjector()
    scheduled = []
    field = {"text": ""}
    probe = lambda full=False: FocusInfo(app="notepad.exe", is_password=False, field_text=field["text"])
    pipe = Pipeline(Config(), SpeechAt(), FakeASR(ok("Send it to Kavia by Friday.")), inj, store, probe=probe, schedule=lambda s, fn: scheduled.append((s, fn)))
    d = pipe.run(speech_audio(), "hold", time.perf_counter(), FocusProbe(lambda: FocusInfo(app="notepad.exe", is_password=False)))
    assert d.status == "pasted" and scheduled and scheduled[0][0] == 10.0
    field["text"] = "Send it to Kavya by Friday. "  # the user fixed the name
    scheduled[0][1]()
    assert [r["term"] for r in store.words()] == ["Kavya"] and store.words()[0]["source"] == "learned"
    row = store.recent(1)[0]
    assert row["edit_rate"] > 0 and row["learned"] == "Kavia -> Kavya"


def test_learning_skips_another_app():
    store = Store(":memory:")
    scheduled = []
    probe = lambda full=False: FocusInfo(app="chrome.exe", field_text="Send it to Kavya by Friday.")
    pipe = Pipeline(Config(), SpeechAt(), FakeASR(ok("Send it to Kavia by Friday.")), FakeInjector(), store, probe=probe, schedule=lambda s, fn: scheduled.append(fn))
    pipe.run(speech_audio(), "hold", time.perf_counter(), FocusProbe(lambda: FocusInfo(app="notepad.exe", is_password=False)))
    scheduled[0]()
    assert store.words() == []


def test_snippet_in_pipeline_survives_cleanup():
    store = Store(":memory:")
    store.add_snippet("my email address", "kavya@example.com")
    inj = FakeInjector()
    Pipeline(Config(), SpeechAt(), FakeASR(ok("my email address")), inj, store).run(speech_audio(), "hold", time.perf_counter())
    assert inj.pasted == ["kavya@example.com "]

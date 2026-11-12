import numpy as np
from fakes import FakeASR, SpeechAt, ok, speech_audio

from flowtype.audio.dsp import to_wav
from flowtype.config import Config
from flowtype.eval import harness
from flowtype.eval.wer import edit_rate, wer
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Store


def make_dataset(tmp_path):
    (tmp_path / "a.wav").write_bytes(to_wav(speech_audio()))
    (tmp_path / "a.txt").write_text("Send it to Kavya Menon by Friday.")
    (tmp_path / "b.wav").write_bytes(to_wav(speech_audio()))
    (tmp_path / "b.txt").write_text("Deploy on Kubernetes tonight.")
    (tmp_path / "noise_room.wav").write_bytes(to_wav(np.random.default_rng(0).normal(0, 0.2, 16000).astype(np.float32)))
    (tmp_path / "noise_room.txt").write_text("")
    (tmp_path / "dataset.toml").write_text('words = ["Kavya Menon", "Kubernetes"]\n[clips.a]\napp = "slack.exe"\n')
    (tmp_path / "variants.toml").write_text('[[variant]]\nname = "base"\n[[variant]]\nname = "strict-vad"\nset = { "vad.min_speech_ms" = 5000 }\n')


def test_score_ignores_case_and_punctuation():
    assert harness.score("Send it, now.", "send it now") == (0.0, 0.0)
    assert harness.score("one two three four", "one two three")[0] == 0.25
    assert wer("a b c d", "a b c") == 0.25 and edit_rate("a b", "a c") == 0.5


def test_dataset_and_variants(tmp_path):
    make_dataset(tmp_path)
    clips, words = harness.load_dataset(tmp_path)
    assert [c.name for c in clips] == ["a", "b", "noise_room"]
    assert clips[0].app == "slack.exe" and clips[2].reference is None and words == ["Kavya Menon", "Kubernetes"]
    vs = harness.load_variants(tmp_path / "variants.toml")
    assert [v.name for v in vs] == ["base", "strict-vad"]
    cfg = harness.apply_overrides(Config(), vs[1].overrides)
    assert cfg.vad.min_speech_ms == 5000 and Config().vad.min_speech_ms == 250


def test_run_summarise_compare(tmp_path):
    make_dataset(tmp_path)
    clips, words = harness.load_dataset(tmp_path)
    asr = FakeASR(ok("Send it to Kavya Menon by Friday."), ok("Deploy on cooper netties tonight."), ok("Thanks for watching!"))

    def factory(cfg, inj):
        return Pipeline(cfg, SpeechAt(), asr, inj, Store(":memory:"))

    results = harness.run(clips, harness.load_variants(tmp_path / "variants.toml"), Config(), factory, words, progress=lambda *_: None)
    s = harness.summarise(results)
    assert s["base"]["clips"] == 3 and s["base"]["hallucinations"] == 0  # the phantom was dropped by the guard / VAD
    assert s["strict-vad"]["dropped_speech"] == 2  # 5 s of speech required: nothing pasted
    assert s["base"]["term_accuracy"] is not None
    cmp = harness.compare(results)
    assert cmp[0]["variant"] == "strict-vad" and cmp[0]["wer_delta"] > 0
    md = harness.report_markdown(s, cmp)
    assert "| base |" in md and "strict-vad" in md
    out = harness.save(results, s, cmp, tmp_path / "reports")
    assert out.exists() and out.with_suffix(".json").exists()


def test_caching_asr():
    inner = FakeASR(ok("x"))
    c = harness.CachingASR(inner)
    a = np.ones(100, np.float32)
    c.transcribe(a, "p", "en"), c.transcribe(a, "p", "en"), c.transcribe(a, "q", "en")
    assert c.calls == 2 and len(inner.calls) == 2


def test_paired_bootstrap():
    mean, lo, hi = harness.paired_bootstrap([0.2] * 20, [0.1] * 20)
    assert abs(mean + 0.1) < 1e-9 and hi < 0

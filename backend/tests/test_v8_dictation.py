"""The Flow-style dictation engine: bias prompt limits and order, hallucination guards, ASR fallback and loop retry,
the AI time budget, and latency / Edit Rate metrics (no text stored)."""

import asyncio

import pytest

from app.dictation import pipeline
from app.dictation.hallucination import clean, has_loop, is_phantom
from app.dictation.prompt import MAX_TOKENS, approx_tokens, build_bias_prompt
from app.dictation.providers import ASRError, ASRResult, Segment


def test_bias_prompt_is_natural_bounded_and_keeps_starred_last():
    many = [f"Term{i}Word" for i in range(400)]
    p = build_bias_prompt(["HackerRank"], many, starred=["Sidhpurwala", "Rizvi College"])
    assert approx_tokens(p) <= MAX_TOKENS
    assert p.startswith("So, um,") and p.rstrip().endswith("I'll explain what I did.")
    assert p.index("Sidhpurwala") > p.index("Term399Word")  # starred terms are last (Whisper weighs later tokens more)
    assert "Term0Word" not in p  # the least relevant are dropped first
    assert "HackerRank" in p and "Talking about HackerRank." in p
    assert "Answer" not in p.split(".")[1]  # no instructions, only lexical context


def test_hallucination_guards():
    assert is_phantom("Thank you for watching!") and is_phantom(" . ") and is_phantom("Subtitles by the Amara.org community")
    assert not is_phantom("Thank you for the question, I built a Flask API.")
    assert has_loop("I built I built I built I built the API") and not has_loop("I built the API and I built the tests")
    res = ASRResult(text="", segments=[Segment("I built it."), Segment("Thank you.", no_speech_prob=0.9, avg_logprob=-1.2), Segment("ok ok ok ok ok ok ok", compression_ratio=3.1)])
    assert clean(res) == "I built it."


class Fake:
    def __init__(self, name, outputs):
        self.name, self.outputs, self.calls = name, list(outputs), []

    async def transcribe(self, audio, filename, prompt, language):
        self.calls.append(prompt)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return ASRResult(text=out, segments=[Segment(out)] if out else [], model=self.name, ms=100)


async def test_fallback_and_loop_retry():
    ctx = pipeline.DictationContext(dictionary=["Flask"])
    bad, good = Fake("primary", [ASRError("timeout")]), Fake("fallback", ["I used Flask."])
    text, model, fallback, retried, _ = await pipeline.transcribe(b"x", "a.wav", ctx, [bad, good])
    assert (text, model, fallback, retried) == ("I used Flask.", "fallback", True, False)
    looping = Fake("primary", ["so so so so so so so so", "I used Flask."])
    text, _, _, retried, _ = await pipeline.transcribe(b"x", "a.wav", ctx, [looping])
    assert text == "I used Flask." and retried and looping.calls[1] == ""  # retried once without the prompt
    with pytest.raises(ASRError):
        await pipeline.transcribe(b"x", "a.wav", ctx, [Fake("a", [ASRError("x")]), Fake("b", [ASRError("y")])])


async def test_ai_pass_respects_the_budget(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "stt_ai_budget_ms", 50)
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["Hi I am Mohsen Sethpurwala from Rizvi College."])])

    async def slow_fix(text, vocab, hint, user_id):
        await asyncio.sleep(0.3)
        return "SHOULD NOT APPEAR", []

    out = await pipeline.run(b"x", "a.wav", pipeline.DictationContext(dictionary=["Mohsin Sidhpurwala"]), None, ai_fix=slow_fix)
    assert out.text == "Hi I am Mohsin Sidhpurwala from Rizvi College." and out.timings["ai_timeout"] is True  # the deterministic text
    called = []

    async def fix(text, vocab, hint, user_id):
        called.append(text)
        return text, []

    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["Yes, Python."])])
    short = await pipeline.run(b"x", "a.wav", pipeline.DictationContext(dictionary=[]), None, ai_fix=fix)
    assert short.text == "Yes, Python." and not called  # fast path: three words or fewer skip the AI pass


async def test_dictation_metrics_store_no_text(authed):
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Dictation, User

    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        rows = [Dictation(user_id=me.id, model="whisper-large-v3-turbo", words=40, asr_ms=ms, server_ms=ms + 100) for ms in (300, 400, 500, 600, 2000)]
        s.add_all(rows)
        await s.flush()
        ids = [str(r.id) for r in rows]
    assert not {c.name for c in Dictation.__table__.columns} & {"text", "raw", "transcript", "audio"}
    await authed.patch(f"/api/stt/dictations/{ids[0]}", json={"client_ms": 650, "edited": True, "edit_ratio": 0.2})
    await authed.patch(f"/api/stt/dictations/{ids[1]}", json={"client_ms": 700, "edited": False, "edit_ratio": 0.0})
    m = (await authed.get("/api/stt/metrics")).json()
    assert m["dictations"] == 5 and m["edit_rate"] == 0.5
    assert m["latency_ms"]["asr_ms"]["p50"] == 500 and m["latency_ms"]["asr_ms"]["p95"] == 2000 and m["latency_ms"]["client_ms"]["p50"] in (650, 700)
    assert (await authed.patch("/api/stt/dictations/not-a-uuid", json={"edited": True})).status_code == 404


# ---------- Phase 2: polished mode (Flow clean-up behind guardrails) ----------

from app.dictation import cleanup as cl  # noqa: E402


def test_strip_fillers_is_conservative():
    assert cl.strip_fillers("um so I I built the uh API, hmm, in Flask") == "So I built the API, in Flask"
    assert cl.strip_fillers("I like Python and you know it") == "I like Python and you know it"  # "like" may be real
    assert cl.strip_fillers("um uh") == "" and cl.strip_fillers("Umbrella hum") == "Umbrella hum"


def test_guard_accepts_a_clean_up_and_rejects_drift():
    said = "um so I I built the the API in Flask no wait FastAPI and it uh handled like two hundred requests a second"
    assert cl.guard(said, "I built the API in FastAPI, and it handled 200 requests a second.", ["FastAPI", "Flask"]).ok
    terms = ["Mohsin Sidhpurwala", "Rizvi College"]
    hi = "hi I'm Mohsen Sethpurwala a second year student at Rizavi college and I built a mess app"
    assert cl.guard(hi, "Hi, I'm Mohsin Sidhpurwala, a second-year student at Rizvi College, and I built a mess app.", terms).ok
    # A name nobody said or listed is an LLM invention.
    v = cl.guard("I worked at a startup on the payments team for a year", "I worked at Razorpay on the payments team for a year.", terms)
    assert not v.ok and "Razorpay" in v.reason
    # It answered instead of formatting.
    q = "why do you want this role"
    assert not cl.guard(q, "Sure! I want this role because it matches my skills and passion for building.", []).ok
    # Too much removed, or too much added.
    long = "I built a dashboard for the hostel mess that showed the menu and let students rate each meal every day"
    assert not cl.guard(long, "I built a dashboard.", []).ok
    assert not cl.guard("I built an app", "I built an app that scaled to a million users across India with great reviews.", []).ok
    assert cl.guard("um", "", []).ok and not cl.guard(long, "", []).ok


def test_prompt_is_small_and_keeps_the_question_out_of_the_answer():
    import json

    m = cl.messages("I built it in Flask", ["Flask"], "Tell me about a project")
    assert len(json.dumps(m)) // 4 < 1100  # free-tier input-token limits: keep each call small
    assert m[0]["role"] == "system" and "not an assistant" in m[0]["content"]
    assert "do not answer it" in m[-1]["content"] and m[-1]["content"].endswith("TRANSCRIPT: I built it in Flask")


async def test_polished_mode_uses_the_clean_up_only_when_it_passes(monkeypatch):
    from app.config import settings

    said = "um so I I built the API in Flask no wait FastAPI and it uh served two hundred students"
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", [said])])
    ctx = pipeline.DictationContext(dictionary=["FastAPI", "Flask"])

    async def good(text, vocab, q):
        return "I built the API in FastAPI, and it served 200 students.", 120, "qwen"

    out = await pipeline.run(b"x", "a.wav", ctx, mode="polished", cleanup_fn=good)
    assert out.text == "I built the API in FastAPI, and it served 200 students." and out.guard == "ok" and out.mode == "polished"
    assert out.raw == said  # the raw words are still available to undo the clean-up

    async def invents(text, vocab, q):
        return "I built the API at Google in FastAPI, and it served 200 students.", 120, "qwen"

    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", [said])])
    out = await pipeline.run(b"x", "a.wav", ctx, mode="polished", cleanup_fn=invents)
    assert out.guard.startswith("rejected") and out.text == "So I built the API in Flask no wait FastAPI and it served two hundred students"

    monkeypatch.setattr(settings, "stt_cleanup_budget_ms", 50)

    async def slow(text, vocab, q):
        await asyncio.sleep(0.3)
        return "LATE", 300, "qwen"

    async def down(text, vocab, q):
        raise RuntimeError("429")

    for fn, why in ((slow, "timeout"), (down, "error")):
        monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", [said])])
        out = await pipeline.run(b"x", "a.wav", ctx, mode="polished", cleanup_fn=fn)
        assert out.guard == why and out.text.startswith("So I built the API in Flask")  # never blocks, never loses words

    called = []

    async def spy(text, vocab, q):
        called.append(text)
        return text, 1, "qwen"

    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["yes python"])])
    out = await pipeline.run(b"x", "a.wav", ctx, mode="polished", cleanup_fn=spy)
    assert out.text == "Yes python." and out.guard == "skipped" and not called  # fast path


async def test_mode_setting_and_cleanup_metrics(authed):
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import Dictation, User

    assert (await authed.get("/api/stt/words")).json()["mode"] == "polished"  # the default
    assert (await authed.put("/api/stt/mode", json={"mode": "verbatim"})).json()["mode"] == "verbatim"
    assert (await authed.get("/api/stt/words")).json()["mode"] == "verbatim"
    assert (await authed.put("/api/stt/mode", json={"mode": "rewrite"})).status_code == 422
    async with session_scope() as s:
        me = (await s.execute(select(User))).scalar_one()
        s.add_all(
            [
                Dictation(user_id=me.id, mode="polished", guard="ok", llm_ms=200, edited=False),
                Dictation(user_id=me.id, mode="polished", guard="ok", llm_ms=300, edited=True),
                Dictation(user_id=me.id, mode="polished", guard="rejected: added 'Google'", llm_ms=250),
                Dictation(user_id=me.id, mode="polished", guard="timeout"),
                Dictation(user_id=me.id, mode="polished", guard="skipped"),
                Dictation(user_id=me.id, mode="verbatim", edited=True),
            ]
        )
    m = (await authed.get("/api/stt/metrics")).json()
    c = m["cleanup"]
    assert c["runs"] == 4 and c["accepted_rate"] == 0.5 and c["guard_rejection_rate"] == 0.25 and c["timeout_rate"] == 0.25
    assert m["edit_rate_by_mode"] == {"polished": 0.5, "verbatim": 1.0}

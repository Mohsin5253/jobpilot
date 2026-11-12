"""Flowtype inside the mock interview: the guards tuned on live Groq output, the sound match, spoken formatting, the
answer-box context, speculative chunks and learning from corrections."""

from app.dictation import cleanup as cl
from app.dictation import pipeline
from app.dictation.context import collect
from app.dictation.hallucination import clean, echoes_prompt, needs_retry
from app.dictation.learn import learn, merge_learned
from app.dictation.matcher import correct, match_score
from app.dictation.providers import ASRResult, Segment


class Fake:
    def __init__(self, name, outputs):
        self.name, self.outputs, self.calls = name, list(outputs), []

    async def transcribe(self, audio, filename, prompt, language):
        self.calls.append(prompt)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, ASRResult):
            return out
        return ASRResult(text=out, segments=[Segment(out)] if out else [], model=self.name, ms=100)


# ---------- the guards ----------


def test_low_confidence_noise_is_dropped_even_when_no_speech_prob_is_zero():
    # Groq's turbo model says no_speech_prob = 0 on pure noise; avg_logprob is what separates it (measured live)
    noise = ASRResult(text="Razorpay, FastAPI.", segments=[Segment("Razorpay, FastAPI.", no_speech_prob=0.0, avg_logprob=-1.3)])
    assert clean(noise) == ""
    speech = ASRResult(text="I built it in FastAPI.", segments=[Segment("I built it in FastAPI.", avg_logprob=-0.2)])
    assert clean(speech) == "I built it in FastAPI."
    assert clean(ASRResult(text="Thank you.")) == ""  # no segments, no confidence: a lone phantom goes


def test_prompt_echo_is_retried_without_the_prompt():
    prompt = "So, um, I'll answer in my own words. I've worked with Razorpay, Zeta Labs and FastAPI."
    assert echoes_prompt("Razorpay, Zeta Labs, FastAPI.", prompt)
    assert not echoes_prompt("I used FastAPI at Razorpay to build the payouts service.", prompt)
    assert needs_retry(ASRResult(text="Razorpay, FastAPI."), prompt) and not needs_retry(ASRResult(text="Razorpay, FastAPI."), "")


async def test_pipeline_retries_an_echo_and_keeps_the_real_words(monkeypatch):
    asr = Fake("m", ["Razorpay, FastAPI.", "I joined Razorpay last May."])
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [asr])
    ctx = pipeline.DictationContext(dictionary=["Razorpay", "FastAPI"])
    out = await pipeline.run(b"x", "a.wav", ctx)
    assert out.text == "I joined Razorpay last May." and out.retried and asr.calls[1] == ""


def test_guard_numbers_and_sound_alike_fixes():
    assert cl.guard("can we move it to four thirty tomorrow", "Can we move it to 4:30 tomorrow?", []).ok
    assert cl.guard("we meet at ten", "We meet at 10:00.", []).ok
    assert cl.guard("I built the API with fast RP and Postgres", "I built the API with FastAPI and Postgres.", []).ok  # live: was rejected
    v = cl.guard("I worked at a startup on payments", "I worked at Razorpay on payments.", [])
    assert not v.ok and "Razorpay" in v.reason
    assert not cl.guard("it handled two hundred requests", "It handled 300 requests.", []).ok
    assert cl.guard("first I cleaned the data second I trained it", "1. I cleaned the data.\n2. I trained it.", []).ok


def test_sound_match_fixes_names_and_spelled_out_identifiers():
    assert match_score("Mohasin Sidpurwala", "Mohsin Sidhpurwala") >= 0.8
    text, fixes = correct("Hi I am Mohasin Sidpurwala from Rizavi College", ["Mohsin Sidhpurwala", "Rizvi College"])
    assert text == "Hi I am Mohsin Sidhpurwala from Rizvi College" and len(fixes) == 2
    text, _ = correct("then I call get user by id to fetch it", ["getUserById"])
    assert text == "then I call getUserById to fetch it"
    assert correct("I like the team", ["Lake"])[0] == "I like the team"  # common words are never rewritten


# ---------- spoken formatting and the answer-box context ----------


async def test_new_paragraph_said_first_survives_the_clean_up(monkeypatch):
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["New paragraph. The second reason is the team, which I liked a lot"])])

    async def tidy(text, vocab, q):
        return "The second reason is the team, which I liked a lot.", 50, "qwen"

    out = await pipeline.run(b"x", "a.wav", pipeline.DictationContext(dictionary=[]), mode="polished", cleanup_fn=tidy)
    assert out.text == "\n\nThe second reason is the team, which I liked a lot." and out.guard == "ok"


def test_context_collects_the_question_the_company_and_the_answer_so_far():
    a = collect(question="Tell me about a time you used Kafka at scale", before="At Zeta Labs we used Kafka and Flink for", company="Razorpay", role="Backend Intern")
    assert {"Razorpay", "Backend Intern", "Zeta Labs"} <= set(a.screen_terms) and a.continues_sentence and a.style == "interview"
    code = collect(question="Explain your approach", before="I wrote max_profit and getUserById", kind="coding")
    assert code.style == "code" and {"max_profit", "getUserById"} <= set(code.identifiers)


async def test_mid_sentence_dictation_continues_it(monkeypatch):
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["And then I deployed it on Render."])])
    ctx = pipeline.DictationContext(dictionary=["Render"], answer=collect(before="I built the backend in FastAPI"))
    out = await pipeline.run(b"x", "a.wav", ctx)
    assert out.text == "and then I deployed it on Render."
    ctx = pipeline.DictationContext(dictionary=["Render"], answer=collect(before="I built the backend in FastAPI."))
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Fake("m", ["And then I deployed it on Render."])])
    assert (await pipeline.run(b"x", "a.wav", ctx)).text == "And then I deployed it on Render."


async def test_answer_so_far_is_the_style_sample_and_screen_terms_reach_the_prompt(monkeypatch):
    asr = Fake("m", ["We sharded the topics."])
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [asr])
    ctx = pipeline.DictationContext(dictionary=[], answer=collect(before="At Zeta Labs we used Kafka and Flink for the event pipeline, and", company="Razorpay"))
    await pipeline.run(b"x", "a.wav", ctx)
    assert asr.calls[0].startswith("At Zeta Labs we used Kafka") and "Razorpay" in asr.calls[0]


# ---------- speculative chunks ----------


async def test_chunks_already_transcribed_are_cleaned_up_with_the_rest(monkeypatch):
    asr = Fake("m", ["and that cut the latency in half"])
    monkeypatch.setattr(pipeline, "asr_chain", lambda: [asr])
    seen = []

    async def tidy(text, vocab, q):
        seen.append(text)
        return "We moved the cache to Redis, and that cut the latency in half.", 80, "qwen"

    ctx = pipeline.DictationContext(dictionary=["Redis"], prefix="um we moved the cache to redis")
    out = await pipeline.run(b"tail", "a.wav", ctx, mode="polished", cleanup_fn=tidy)
    assert seen == ["um we moved the cache to Redis and that cut the latency in half"] and out.guard == "ok"
    assert len(asr.calls) == 1  # only the tail went to ASR at release
    ctx = pipeline.DictationContext(dictionary=[], prefix="I led the migration")
    assert (await pipeline.run(None, "a.wav", ctx)).text == "I led the migration"  # nothing left after the last chunk


# ---------- learning from corrections ----------


def test_learns_a_corrected_spelling_but_not_a_rewrite():
    res = learn("Please loop in Ishan on the design review.", "Please loop in Ishaan on the design review. Thanks!")
    assert res.corrections == [("Ishan", "Ishaan")]
    rewrite = learn("I built a dashboard for the hostel mess.", "My favourite project was a payments app at Zeta Labs.")
    assert rewrite is None or not rewrite.corrections
    assert not learn("I built it in Flask.", "I built it in flask quickly.").corrections  # lower-case, common: not a term
    assert merge_learned(["Kavya", "Zeta"], ["Ishaan", "Kavya"], own=["Zeta"]) == ["Ishaan", "Kavya"]  # newest first, no repeats, not your own words


# ---------- the API ----------


async def test_chunk_and_final_endpoints_and_learning(authed, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "groq_api_key", "test")
    prompts = []

    class Echo:
        name = "whisper-large-v3-turbo"

        async def transcribe(self, audio, filename, prompt, language):
            prompts.append(prompt)
            text = "we moved the cache to redis" if filename.startswith("chunk") else "and it halved the latency"
            return ASRResult(text=text, segments=[Segment(text, avg_logprob=-0.2)], model=self.name, ms=90)

    monkeypatch.setattr(pipeline, "asr_chain", lambda: [Echo()])
    wav = ("a.wav", b"\0" * 4000, "audio/wav")
    form = {"hint": "Tell me about a performance win", "company": "Razorpay", "role": "Backend Intern", "before": "At Zeta Labs,"}
    c = (await authed.post("/api/stt/chunk", files={"audio": wav}, data=form)).json()
    assert c["text"] == "we moved the cache to redis"
    r = await authed.post("/api/stt", files={"audio": wav}, data={**form, "prefix": c["text"], "chunks": "1", "mode": "verbatim"})
    body = r.json()
    assert r.status_code == 200 and body["text"] == "we moved the cache to redis and it halved the latency" and body["timings"]["chunks"] == 1
    assert "Razorpay" in prompts[0] and "Zeta Labs" in prompts[0]
    # At submit the browser sends the take and the final answer: the corrected spelling is learned, the text isn't kept.
    patch = await authed.patch(f"/api/stt/dictations/{body['dictation_id']}", json={"edited": True, "edit_ratio": 0.1, "dictated": "Please loop in Ishan on the review.", "final": "Please loop in Ishaan on the review."})
    assert patch.json()["learned"] == ["Ishaan"]
    words = (await authed.get("/api/stt/words")).json()
    assert words["learned"] == ["Ishaan"]
    assert (await authed.put("/api/stt/learned", json={"words": []})).json()["learned"] == []
    # prefix only (the last chunk ended the answer): no audio needed
    r = await authed.post("/api/stt", data={**form, "prefix": "I led the migration", "mode": "verbatim"})
    assert r.json()["text"] == "I led the migration"

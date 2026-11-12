import pytest

from flowtype.asr.base import ASRResult, Segment
from flowtype.guard.hallucination import clean, echoes_prompt, has_loop, is_stock, needs_retry


def res(*segs: Segment, text: str | None = None) -> ASRResult:
    return ASRResult(text=text if text is not None else " ".join(s.text for s in segs), segments=list(segs))


@pytest.mark.parametrize("phrase", ["Thanks for watching!", "Thank you for watching.", "Please subscribe.", "Subtitles by the Amara.org community",
                                    "[Music]", "(applause)", "♪♪", "...", "Like and subscribe", "Transcribed by ESO"])
def test_stock_phrases_always_dropped(phrase):
    assert is_stock(phrase)
    assert clean(res(Segment(phrase))).text == ""


def test_real_speech_is_kept():
    r = res(Segment("Please send the report by Friday."), Segment("Thanks, Mohsin."))
    out = clean(r)
    assert out.text == "Please send the report by Friday. Thanks, Mohsin."
    assert out.dropped == []


def test_weak_phrase_kept_when_whisper_is_confident():
    assert clean(res(Segment("Thank you.", no_speech_prob=0.02, avg_logprob=-0.2))).text == "Thank you."
    assert clean(res(Segment("Okay.", no_speech_prob=0.05, avg_logprob=-0.3))).text == "Okay."


def test_weak_phrase_dropped_when_whisper_is_unsure():
    out = clean(res(Segment("Thank you.", no_speech_prob=0.5, avg_logprob=-0.4)))
    assert out.text == "" and out.dropped == ["weak"]


def test_no_speech_segment_dropped():
    r = res(Segment("Meeting at five.", no_speech_prob=0.01, avg_logprob=-0.2), Segment("you you", no_speech_prob=0.9, avg_logprob=-1.2))
    out = clean(r)
    assert out.text == "Meeting at five."
    assert "no_speech" in out.dropped


def test_high_compression_ratio_dropped():
    out = clean(res(Segment("Hello."), Segment("the the the the the the the", compression_ratio=3.1)))
    assert out.text == "Hello." and "loop" in out.dropped


def test_loop_detection():
    assert has_loop("I am going I am going I am going I am going")
    assert has_loop("no no no no")
    assert not has_loop("no, no, I said no")
    assert not has_loop("We will, we will rock you.")
    assert not has_loop(".") and not has_loop("")


def test_no_segments_falls_back_to_text():
    assert clean(ASRResult(text="Thanks for watching.")).text == ""
    assert clean(ASRResult(text="Send it now.")).text == "Send it now."


def test_retry_on_loop_or_echo_but_only_with_a_prompt():
    looping = res(Segment("okay okay okay okay okay", compression_ratio=2.6))
    prompt = "So, um, I'll say it in my own words. I often mention Kafka and Flowtype."
    assert needs_retry(looping, prompt)
    assert not needs_retry(looping, "")
    echo = res(Segment("I'll say it in my own words. I often mention Kafka"))
    assert needs_retry(echo, prompt)
    assert not needs_retry(res(Segment("Please book a table at Kafka cafe.")), prompt)


def test_echo_short():
    p = "So, um, I'll say it in my own words."
    assert echoes_prompt("in my own words", p)
    assert echoes_prompt("my words", p)  # only prompt words: retried without the prompt (harmless for real speech)
    assert not echoes_prompt("in my own way", p)
    assert not echoes_prompt("book my words", p)


# Real Groq whisper-large-v3-turbo output, captured on the synthetic eval set (segment text, avg_logprob).
PROMPT = "So, um, I'll say it in my own words. I often mention Kavya Menon, Kubernetes, FastAPI, Zeta Labs and Razorpay."
LIVE_NOISE_WITH_PROMPT = [("Razorpay, Zeta Labs, FastAPI, Kubernetes", -0.554), ("Razorpay", -0.406), ("Razorpay.", -0.529)]
LIVE_NOISE_NO_PROMPT = [("HAAAHHHHH!", -1.644), (".", -0.774), ("So", -0.879)]
LIVE_SPEECH = [("Running 10 minutes late, start without me.", -0.153), ("Men abhi office pohunch raha hoon, 10 minutes may call karta hoon.", -0.37),
               ("Kalka meeting cancel ho gaya, so let's sync on Monday.", -0.276), ("Razorpay webhooks failed twice last night, so I added a retry.", -0.135)]


def test_live_noise_with_prompt_is_retried():
    for text, lp in LIVE_NOISE_WITH_PROMPT:
        assert needs_retry(res(Segment(text, avg_logprob=lp)), PROMPT), text


def test_live_noise_without_prompt_is_dropped():
    for text, lp in LIVE_NOISE_NO_PROMPT:
        assert clean(res(Segment(text, avg_logprob=lp))).text == "", text


def test_live_speech_is_kept_and_not_retried():
    for text, lp in LIVE_SPEECH:
        r = res(Segment(text, avg_logprob=lp))
        assert clean(r).text == text and not needs_retry(r, PROMPT), text

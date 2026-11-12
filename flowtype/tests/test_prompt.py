import random
from functools import partial

import pytest

from flowtype.asr import prompt as prompt_mod
from flowtype.asr.prompt import BUDGET, MAX_TOKENS, STYLES, approx_tokens

# Deterministic: always the estimate, whether or not Whisper's tokenizer is cached on this machine.
build_bias_prompt = partial(prompt_mod.build_bias_prompt, count=approx_tokens)


def test_style_sample_alone_when_no_words():
    assert build_bias_prompt([]) == STYLES["en-IN"]
    assert build_bias_prompt([], style="hinglish") == STYLES["hinglish"]


def test_stays_within_token_limit_with_a_huge_dictionary():
    words = [f"Term{i} Sidhpurwala" for i in range(2000)]
    p = build_bias_prompt(words, starred=["Flowtype"], context_terms=["Notepad", "Quarterly Report"])
    assert approx_tokens(p) <= BUDGET < MAX_TOKENS
    assert "Flowtype" in p


def test_budget_is_respected_for_every_size():
    for n in range(0, 300, 7):
        p = build_bias_prompt([f"Word{i}" for i in range(n)], starred=["Alpha", "Beta"])
        assert approx_tokens(p) <= BUDGET


def test_starred_terms_survive_and_come_last():
    words = [f"filler{i}" for i in range(500)]
    p = build_bias_prompt(words, starred=["Mohsin", "Rizvi College"])
    assert p.rstrip(".").endswith("Mohsin and Rizvi College")


def test_least_relevant_dropped_first():
    words = ["MostRelevant"] + [f"filler{i}" for i in range(400)]  # most relevant first
    p = build_bias_prompt(words)
    assert "MostRelevant" in p
    assert "filler399" not in p


def test_dedupes_case_insensitively_and_starred_wins():
    p = build_bias_prompt(["GitHub", "github", "Kafka"], starred=["GITHUB"])
    assert p.lower().count("github") == 1
    assert "GITHUB" in p


def test_even_starred_terms_are_trimmed_when_they_alone_overflow():
    starred = [f"Verylongpropername{i}" for i in range(200)]
    p = build_bias_prompt([], starred=starred)
    assert approx_tokens(p) <= BUDGET


def test_token_estimate_is_pessimistic_for_names_and_unicode():
    assert approx_tokens("Sidhpurwala") >= 3
    assert approx_tokens("नमस्ते") >= 6
    assert approx_tokens("CI/CD, 2026.") >= 6


NAMEY = "ka kha ga sha zh pur wala esh ika ndr aj iy eep oo bh dh th kr vy ksh".split()


def _names(rng, n):
    return ["".join(rng.choice(NAMEY) for _ in range(rng.randint(2, 5))).capitalize() + rng.choice(["", " QA", "2026", "/CD", ".js"]) for _ in range(n)]


@pytest.mark.skipif(prompt_mod.exact_counter() is None, reason="Whisper tokenizer not cached (run: python -m flowtype fetch-tokenizer)")
def test_estimate_never_lets_a_prompt_exceed_whispers_real_limit():
    real = prompt_mod.exact_counter()
    rng = random.Random(7)
    for _ in range(200):
        p = build_bias_prompt(_names(rng, 300), starred=_names(rng, 3), style=rng.choice(["en-IN", "hinglish"]))
        assert real(p) <= MAX_TOKENS


@pytest.mark.skipif(prompt_mod.exact_counter() is None, reason="Whisper tokenizer not cached")
def test_exact_counter_fills_the_budget():
    real = prompt_mod.exact_counter()
    p = prompt_mod.build_bias_prompt(_names(random.Random(3), 300), count=real)
    assert BUDGET - 15 <= real(p) <= BUDGET

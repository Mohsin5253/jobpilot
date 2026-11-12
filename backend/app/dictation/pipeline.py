"""The dictation pipeline: ASR (with fallback) → hallucination filter (with one retry on a loop) → deterministic
fixes (term spellings, phonetic dictionary match) → then, by mode:

- verbatim ("word for word"): a constrained AI fix that may only respell your vocabulary words;
- polished: the Flow clean-up (fillers, false starts and self-corrections removed, punctuation, lists, numbers) under
  a strict time budget, checked by a guardrail validator. Any failure (timeout, rate limit, a rewrite that moved too
  far, added a name or reads like a reply) falls back to the deterministic text with only um / uh / stutters removed.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from app.config import settings
from app.dictation import cleanup as cleanup_mod
from app.dictation.hallucination import clean, has_loop
from app.dictation.prompt import build_bias_prompt
from app.dictation.providers import ASRError, ASRProvider, asr_chain
from app.dictation.terms import polish
from app.services.speech_vocab import correct


@dataclass
class DictationContext:
    dictionary: list[str]
    context_terms: list[str] = field(default_factory=list)
    starred: list[str] = field(default_factory=list)
    language: str | None = "en"
    hint: str = ""  # the question being answered (for the AI fix only, never in the Whisper prompt)


@dataclass
class DictationResult:
    text: str
    raw: str
    corrections: list[dict]
    model: str
    fallback: bool = False
    retried: bool = False
    timings: dict = field(default_factory=dict)
    mode: str = "verbatim"
    guard: str = ""  # polished: ok | skipped | timeout | error | rejected: <reason>
    llm_model: str = ""

MODES = ("polished", "verbatim")


async def transcribe(audio: bytes, filename: str, ctx: DictationContext, providers: list[ASRProvider] | None = None) -> tuple[str, str, bool, bool, int]:
    """(clean text, model, used fallback, retried without prompt, asr ms)."""
    prompt = build_bias_prompt(ctx.context_terms, ctx.dictionary, ctx.starred)
    providers = providers or asr_chain()
    last: Exception | None = None
    for i, p in enumerate(providers):
        try:
            res = await p.transcribe(audio, filename, prompt, ctx.language)
        except ASRError as exc:
            last = exc
            continue
        text, ms, retried = clean(res), res.ms, False
        if text and has_loop(text):  # a biasing prompt can seed a loop: once more without it
            again = await p.transcribe(audio, filename, "", ctx.language)
            text, ms, retried = clean(again), ms + again.ms, True
        return text, p.name, i > 0, retried, ms
    raise ASRError(str(last) if last else "no provider")


async def run(audio: bytes, filename: str, ctx: DictationContext, user_id=None, ai_fix=None, mode: str = "verbatim", cleanup_fn=None) -> DictationResult:
    t0 = time.perf_counter()
    raw, model, fallback, retried, asr_ms = await transcribe(audio, filename, ctx)
    t1 = time.perf_counter()
    text = polish(raw)
    vocab = [*ctx.starred, *ctx.dictionary, *ctx.context_terms]
    text, fixes = correct(text, vocab)
    t2 = time.perf_counter()
    ai: list[dict] = []
    ai_timeout = False
    guard, llm_model = "", ""
    mode = mode if mode in MODES else "verbatim"
    if mode == "polished":
        text, guard, llm_model = await _polish(text, vocab, ctx.hint, cleanup_fn or cleanup_mod.cleanup)
        ai_timeout = guard == "timeout"
    # Fast path: very short answers skip the AI pass. Otherwise it gets a strict budget; past it, the
    # deterministic text is used (latency budget: ~700 ms from release to text).
    elif ai_fix is not None and len(text.split()) > 3:
        try:
            text, ai = await asyncio.wait_for(ai_fix(text, vocab, ctx.hint, user_id), timeout=settings.stt_ai_budget_ms / 1000)
        except asyncio.TimeoutError:
            ai_timeout = True
    t3 = time.perf_counter()
    keep_lines = mode == "polished"  # a numbered list keeps its line breaks
    out = re.sub(r"[ \t]+", " ", text) if keep_lines else re.sub(r"\s+", " ", text)
    return DictationResult(
        text=re.sub(r" *\n *", "\n", out).strip(),
        raw=raw,
        corrections=[*fixes, *ai],
        model=model,
        fallback=fallback,
        retried=retried,
        mode=mode,
        guard=guard,
        llm_model=llm_model,
        timings={"ai_timeout": ai_timeout, "asr_ms": asr_ms, "upload_and_asr_ms": int((t1 - t0) * 1000), "fixes_ms": int((t2 - t1) * 1000), "ai_ms": int((t3 - t2) * 1000), "server_ms": int((t3 - t0) * 1000)},
    )


async def _polish(text: str, vocab: list[str], question: str, cleanup_fn) -> tuple[str, str, str]:
    """(text, guard result, clean-up model). Never raises: every failure returns the deterministic pre-pass."""
    fallback = cleanup_mod.strip_fillers(text)
    if not fallback:
        return "", "skipped", ""
    # Fast path: a few words with nothing to clean only need a capital and a full stop.
    if len(fallback.split()) <= 3 and not cleanup_mod.has_fillers(text):
        return fallback if fallback[-1] in ".?!" else fallback + ".", "skipped", ""
    try:
        out, _ms, used = await asyncio.wait_for(cleanup_fn(text, vocab, question), timeout=settings.stt_cleanup_budget_ms / 1000)
    except asyncio.TimeoutError:
        return fallback, "timeout", ""
    except Exception:  # noqa: BLE001 - rate limit, provider down: the deterministic text is always fine
        return fallback, "error", ""
    verdict = cleanup_mod.guard(text, out, vocab)
    if not verdict.ok:
        return fallback, f"rejected: {verdict.reason}"[:40], used
    return out, "ok", used

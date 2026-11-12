"""The dictation pipeline (Flowtype's, inside the mock interview): ASR (with fallback) → hallucination filter (one
retry without the prompt on a loop or a prompt echo) → spoken formatting ("new paragraph") → deterministic fixes (term
spellings, the sound match against your dictionary and the identifiers on screen) → then, by mode:

- verbatim ("word for word"): a constrained AI fix that may only respell your vocabulary words;
- polished: the Flow clean-up (fillers, false starts and self-corrections removed, punctuation, lists, numbers) under
  a strict time budget, checked by a guardrail validator. Any failure (timeout, rate limit, a rewrite that moved too
  far, added a name or reads like a reply) falls back to the deterministic text with only um / uh / stutters removed.

Long answers arrive in pieces: the browser sends finished stretches of speech while you're still talking
(speculative chunks, transcribed by `transcribe_chunk`), and at release only the rest is left to transcribe. The
chunks' text comes back as `prefix` and is cleaned up together with the rest.
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from functools import partial

from app.config import settings
from app.dictation import cleanup as cleanup_mod
from app.dictation.context import AnswerContext
from app.dictation.formatting import apply_spoken_formatting, split_breaks
from app.dictation.hallucination import clean, needs_retry
from app.dictation.matcher import correct
from app.dictation.prompt import STYLE_SAMPLE, build_bias_prompt
from app.dictation.providers import ASRError, ASRProvider, asr_chain
from app.dictation.terms import polish
from app.services.speech_vocab import COMMON


@dataclass
class DictationContext:
    dictionary: list[str]
    context_terms: list[str] = field(default_factory=list)
    starred: list[str] = field(default_factory=list)
    language: str | None = "en"
    hint: str = ""  # the question being answered (for the AI fix only, never in the Whisper prompt)
    answer: AnswerContext | None = None  # the answer box around the cursor, the round (see app.dictation.context)
    prefix: str = ""  # the text of the speculative chunks already transcribed while the candidate was talking

    @property
    def vocab(self) -> list[str]:
        idents = self.answer.identifiers if self.answer else []
        return list(dict.fromkeys([*self.starred, *self.dictionary, *self.context_terms, *idents]))

    @property
    def prompt(self) -> str:
        sample = self.answer.style_sample if self.answer and self.answer.style_sample else STYLE_SAMPLE
        terms = [*self.context_terms, *(self.answer.screen_terms if self.answer else []), *(self.answer.identifiers if self.answer else [])]
        return build_bias_prompt(list(dict.fromkeys(terms)), self.dictionary, self.starred, style_sample=sample)


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
    dropped: list[str] = field(default_factory=list)


MODES = ("polished", "verbatim")


async def transcribe(audio: bytes, filename: str, ctx: DictationContext, providers: list[ASRProvider] | None = None) -> tuple[str, str, bool, bool, int]:
    """(clean text, model, used fallback, retried without prompt, asr ms)."""
    prompt = ctx.prompt
    providers = providers or asr_chain()
    last: Exception | None = None
    for i, p in enumerate(providers):
        try:
            res = await p.transcribe(audio, filename, prompt, ctx.language)
        except ASRError as exc:
            last = exc
            continue
        ms, retried = res.ms, False
        if needs_retry(res, prompt):  # a bias prompt can seed a loop, or come back instead of the speech
            again = await p.transcribe(audio, filename, "", ctx.language)
            res, ms, retried = again, ms + again.ms, True
        return clean(res), p.name, i > 0, retried, ms
    raise ASRError(str(last) if last else "no provider")


async def transcribe_chunk(audio: bytes, filename: str, ctx: DictationContext) -> tuple[str, int]:
    """One speculative chunk: ASR and the hallucination filter only (the clean-up runs once, over the whole answer)."""
    text, _model, _fb, _retried, ms = await transcribe(audio, filename, ctx)
    return text, ms


async def run(audio: bytes | None, filename: str, ctx: DictationContext, user_id=None, ai_fix=None, mode: str = "verbatim", cleanup_fn=None) -> DictationResult:
    t0 = time.perf_counter()
    tail, model, fallback, retried, asr_ms = ("", "", False, False, 0)
    if audio:
        tail, model, fallback, retried, asr_ms = await transcribe(audio, filename, ctx)
    raw = " ".join(t for t in (ctx.prefix.strip(), tail) if t)
    t1 = time.perf_counter()
    lead, body, trail = split_breaks(apply_spoken_formatting(raw))
    text = polish(body)
    vocab = ctx.vocab
    text, fixes = correct(text, vocab)
    t2 = time.perf_counter()
    ai: list[dict] = []
    ai_timeout = False
    guard, llm_model = "", ""
    mode = mode if mode in MODES else "verbatim"
    style = ctx.answer.style if ctx.answer else "interview"
    if mode == "polished" and text:
        text, guard, llm_model = await _polish(text, vocab, ctx.hint, cleanup_fn or partial(cleanup_mod.cleanup, style=style))
        ai_timeout = guard == "timeout"
    # Fast path: very short answers skip the AI pass. Otherwise it gets a strict budget; past it, the
    # deterministic text is used (latency budget: ~700 ms from release to text).
    elif ai_fix is not None and len(text.split()) > 3:
        try:
            text, ai = await asyncio.wait_for(ai_fix(text, vocab, ctx.hint, user_id), timeout=settings.stt_ai_budget_ms / 1000)
        except asyncio.TimeoutError:
            ai_timeout = True
    t3 = time.perf_counter()
    keep_lines = mode == "polished" or "\n" in text  # a numbered list keeps its line breaks
    out = re.sub(r"[ \t]+", " ", text) if keep_lines else re.sub(r"\s+", " ", text)
    out = re.sub(r" *\n *", "\n", out).strip()
    if ctx.answer is not None and ctx.answer.continues_sentence and not lead:
        out = _continue_sentence(out, vocab)
    return DictationResult(
        text=lead + out + trail,
        raw=raw,
        corrections=[*fixes, *ai],
        model=model or (settings.stt_model if ctx.prefix else ""),
        fallback=fallback,
        retried=retried,
        mode=mode,
        guard=guard,
        llm_model=llm_model,
        timings={"ai_timeout": ai_timeout, "asr_ms": asr_ms, "upload_and_asr_ms": int((t1 - t0) * 1000), "fixes_ms": int((t2 - t1) * 1000), "ai_ms": int((t3 - t2) * 1000), "server_ms": int((t3 - t0) * 1000)},
    )


def _continue_sentence(text: str, vocab: list[str]) -> str:
    """The cursor is mid-sentence: "and then I deployed it" continues it, so a capital on an ordinary first word goes.
    Names, terms and "I" keep theirs."""
    m = re.match(r"([A-Z][a-z']*)\b", text)
    if not m:
        return text
    w = m.group(1)
    if w in ("I", "I'm", "I've", "I'll", "I'd") or w.lower() not in COMMON or any(w == t.split()[0] for t in vocab if t):
        return text
    return w.lower() + text[len(w) :]


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

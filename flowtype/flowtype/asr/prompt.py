"""The Whisper bias prompt (ported from JobPilot's dictation engine).

Whisper reads only the last ~224 tokens of a prompt (Groq rejects longer ones) and weighs later tokens more, so the
order is: a short style sample in the speaker's voice, then terms from the context (Phase 2: the focused app and
window), then the personal dictionary ranked by relevance with starred terms LAST. It's written as natural
sentences, never as instructions: it's a lexical bias, not a chat prompt."""

import math
import re
from typing import Callable

MAX_TOKENS = 224
# A margin below the hard limit: the style sample and joining words are counted too, and the estimate may be in use.
BUDGET = 210

STYLES = {
    # Fillers keep Whisper verbatim; commas and full stops teach it to punctuate.
    "en-IN": "So, um, I'll say it in my own words.",
    # Romanised Hindi in the prompt keeps Hinglish in Roman script instead of Devanagari or a translation.
    "hinglish": "Haan, toh main bol raha tha ki, um, yeh kaam kal tak ho jayega.",
}

_PIECE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def approx_tokens(text: str) -> int:
    """A deliberately pessimistic count of Whisper tokens, used when the real tokenizer isn't on this machine.
    Calibrated against Whisper's tokenizer on Indian names and transliterations (which split into many short
    tokens): about 2.5 letters per token, an extra token for a capital, digit runs in pairs, each punctuation mark
    one token, and non-ASCII one token per UTF-8 byte. It over-counts plain English roughly 2x, never under-counts."""
    n = 0
    for piece in _PIECE.findall(text):
        if piece.isascii() and piece.isalpha():
            n += max(1, math.ceil(len(piece) / 2.5)) + (1 if piece[0].isupper() else 0)
        elif piece.isdigit():
            n += math.ceil(len(piece) / 2)
        else:
            n += len(piece.encode("utf-8")) if not piece.isascii() else 1
    return n


TOKENIZER_REPO = "openai/whisper-large-v3-turbo"
_counter: Callable[[str], int] | None = None


def exact_counter() -> Callable[[str], int] | None:
    """Whisper's own tokenizer, if `flowtype fetch-tokenizer` has cached it. Never touches the network."""
    try:
        from huggingface_hub import try_to_load_from_cache
        from tokenizers import Tokenizer

        path = try_to_load_from_cache(TOKENIZER_REPO, "tokenizer.json")
        if not isinstance(path, str):
            return None
        tok = Tokenizer.from_file(path)
        return lambda text: len(tok.encode(text, add_special_tokens=False).ids)
    except Exception:
        return None


def count_tokens(text: str) -> int:
    global _counter
    if _counter is None:
        _counter = exact_counter() or approx_tokens
    return _counter(text)


def build_bias_prompt(
    dictionary: list[str],
    starred: list[str] | None = None,
    context_terms: list[str] | None = None,
    style: str = "en-IN",
    budget: int = BUDGET,
    count: Callable[[str], int] | None = None,
) -> str:
    """A natural-sentence prompt within the token budget. `dictionary` is ordered most relevant first. Terms are
    de-duplicated (case-insensitively); when the budget is tight the least relevant are dropped first, so starred
    terms are the last to go."""
    style_sample = STYLES.get(style, STYLES["en-IN"])
    starred = _unique(starred or [], set())
    seen = {s.lower() for s in starred}
    ctx = _unique(context_terms or [], seen)
    seen |= {t.lower() for t in ctx}
    words = list(reversed(_unique(dictionary, seen)))  # least relevant first, so the most relevant sit nearest the end

    def render(ctx_: list[str], words_: list[str], starred_: list[str]) -> str:
        parts = [style_sample]
        if ctx_:
            parts.append("This is about " + _join(ctx_) + ".")
        tail = [*words_, *starred_]
        if tail:
            parts.append("I often mention " + _join(tail) + ".")
        return " ".join(parts)

    text = render(ctx, words, starred)
    count = count or count_tokens
    while count(text) > budget and (words or ctx or starred):
        if words:
            words = words[1:]
        elif ctx:
            ctx = ctx[1:]
        else:
            starred = starred[1:]
        text = render(ctx, words, starred)
    return text


def _unique(items: list[str], seen: set[str]) -> list[str]:
    out: list[str] = []
    for t in items:
        t = re.sub(r"\s+", " ", (t or "").strip())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

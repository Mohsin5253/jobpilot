"""The Whisper biasing prompt. Whisper reads only the last ~224 tokens and weighs later tokens more, so the order is:
a short style sample in the speaker's voice, then terms from the context (the question, the job), then the personal
dictionary ranked by relevance with starred terms LAST. It's written as natural sentences, never as instructions:
it's a lexical bias, not a chat prompt."""

import re

MAX_TOKENS = 224
STYLE_SAMPLE = "So, um, I'll answer in my own words."


def approx_tokens(text: str) -> int:
    """Whisper's tokenizer is ~4 characters per token for English; words with capitals and digits cost more."""
    return sum(max(1, round(len(w) / 4)) + (1 if re.search(r"[A-Z0-9]", w) else 0) for w in text.split())


def build_bias_prompt(context_terms: list[str], dictionary: list[str], starred: list[str] | None = None, style_sample: str = STYLE_SAMPLE) -> str:
    """Natural-sentence prompt within the token budget. Terms are de-duplicated; when the budget is tight, the
    least relevant are dropped first (from the front), so starred terms always survive."""
    starred = [s for s in dict.fromkeys(starred or []) if s.strip()]
    seen = {s.lower() for s in starred}
    ctx = [t for t in dict.fromkeys(context_terms) if t.strip() and t.lower() not in seen]
    seen |= {t.lower() for t in ctx}
    words = [t for t in dict.fromkeys(dictionary) if t.strip() and t.lower() not in seen]

    def render(ctx_: list[str], words_: list[str]) -> str:
        parts = [style_sample]
        if ctx_:
            parts.append("Talking about " + _join(ctx_) + ".")
        tail = [*words_, *starred]
        if tail:
            parts.append("I've worked with " + _join(tail) + ", and, uh, I'll explain what I did.")
        return " ".join(parts)

    text = render(ctx, words)
    while approx_tokens(text) > MAX_TOKENS and (words or ctx):
        if words:
            words = words[1:]  # least relevant first
        else:
            ctx = ctx[1:]
        text = render(ctx, words)
    return text


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

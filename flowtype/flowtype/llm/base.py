"""The LLM interface used by the clean-up pass (Phase 2). Phase 1 ships the interface and a Groq implementation;
the pipeline doesn't call it yet."""

from typing import Protocol


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        """One chat completion. Raises LLMError on failure so the caller can paste the un-cleaned text instead."""
        ...

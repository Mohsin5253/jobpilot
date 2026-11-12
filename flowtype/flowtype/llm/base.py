"""The LLM interface used by the clean-up pass and command mode."""

from typing import Protocol


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    def __init__(self, retry_after_s: float):
        super().__init__(f"rate limited for {retry_after_s:.0f}s")
        self.retry_after_s = retry_after_s


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        """One chat completion. Raises LLMError on failure so the caller can paste the un-cleaned text instead."""
        ...

    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.0, timeout_s: float | None = None) -> str:
        """The same with a full message list (few-shot examples)."""
        ...

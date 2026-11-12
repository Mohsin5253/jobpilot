"""Chat completions on Groq (OpenAI-compatible). Model names come from config. Reasoning models get
`reasoning_effort` and any <think> block is stripped."""

import re
import time

import httpx

from flowtype.llm.base import LLMError, RateLimited


class GroqLLM:
    def __init__(self, api_key: str, model: str, timeout_s: float = 6.0, base_url: str = "https://api.groq.com/openai/v1", reasoning: str = ""):
        self.name = model
        self.reasoning = reasoning
        self.timeout_s = timeout_s
        self._client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout_s, connect=4.0), headers={"Authorization": f"Bearer {api_key}"})

    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        return self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens, temperature=temperature)

    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.0, timeout_s: float | None = None) -> str:
        body = {"model": self.name, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
            if self.reasoning != "none":
                body["max_tokens"] = max_tokens + 400  # room to think
        try:
            r = self._client.post("/chat/completions", json=body, timeout=timeout_s or self.timeout_s)
        except httpx.HTTPError as exc:
            raise LLMError(type(exc).__name__) from exc
        if r.status_code == 429:
            raise RateLimited(_retry_after(r))
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}")
        try:
            out = r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("malformed response") from exc
        return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()

    def warm(self) -> None:
        try:
            self._client.get("/models", timeout=4.0)
        except httpx.HTTPError:
            pass

    def close(self) -> None:
        self._client.close()


def _retry_after(r: httpx.Response) -> float:
    try:
        return min(60.0, float(r.headers.get("retry-after") or 10))
    except ValueError:
        return 10.0


class ModelChain:
    """Try each model in turn. A model that answered 429 is skipped until its retry-after has passed, so a busy
    minute costs no latency."""

    def __init__(self, models: list):
        self.models = models
        self.name = "+".join(m.name for m in models)
        self._cooldown: dict[str, float] = {}

    def chat(self, messages: list[dict], *, max_tokens: int = 512, temperature: float = 0.0, timeout_s: float | None = None) -> str:
        return self.chat_with_model(messages, max_tokens=max_tokens, temperature=temperature, timeout_s=timeout_s)[0]

    def chat_with_model(self, messages, *, max_tokens=512, temperature=0.0, timeout_s=None) -> tuple[str, str]:
        last: Exception = LLMError("every model is cooling down after a rate limit")
        now = time.monotonic()
        for m in self.models:
            if self._cooldown.get(m.name, 0) > now:
                continue
            try:
                return m.chat(messages, max_tokens=max_tokens, temperature=temperature, timeout_s=timeout_s), m.name
            except RateLimited as exc:
                self._cooldown[m.name] = time.monotonic() + exc.retry_after_s
                last = exc
            except LLMError as exc:
                last = exc
        raise last

    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        return self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens, temperature=temperature)

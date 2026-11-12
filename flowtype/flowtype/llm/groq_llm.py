"""Chat completions on Groq (OpenAI-compatible). The model name comes from config. Used by the Phase 2 clean-up pass."""

import httpx

from flowtype.llm.base import LLMError


class GroqLLM:
    def __init__(self, api_key: str, model: str, timeout_s: float = 6.0, base_url: str = "https://api.groq.com/openai/v1"):
        self.name = model
        self._client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(timeout_s, connect=4.0), headers={"Authorization": f"Bearer {api_key}"})

    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str:
        body = {
            "model": self.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            r = self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise LLMError(type(exc).__name__) from exc
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}")
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("malformed response") from exc

    def close(self) -> None:
        self._client.close()

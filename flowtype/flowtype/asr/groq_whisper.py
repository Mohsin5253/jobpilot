"""Whisper on Groq (OpenAI-compatible endpoint). temperature 0, language pinned, verbose_json so each segment carries
no_speech_prob / avg_logprob / compression_ratio for the hallucination guard. One HTTP client is reused so the TLS
connection stays warm between dictations."""

import time

import httpx
import numpy as np

from flowtype.asr.base import ASRError, ASRResult, Segment
from flowtype.audio.dsp import to_wav


class GroqWhisper:
    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo", timeout_s: float = 10.0, base_url: str = "https://api.groq.com/openai/v1"):
        self.name = model
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=4.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def warm(self) -> None:
        """Open the connection ahead of the first dictation (saves the TLS handshake on it)."""
        try:
            self._client.get("/models", timeout=4.0)
        except httpx.HTTPError:
            pass

    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult:
        data = {"model": self.name, "temperature": "0", "response_format": "verbose_json"}
        if lang:
            data["language"] = lang
        if prompt:
            data["prompt"] = prompt
        wav = to_wav(audio)
        t0 = time.perf_counter()
        last: Exception | None = None
        for attempt in range(2):  # one retry on a network error or a 5xx; 4xx means our request is wrong
            try:
                r = self._client.post("/audio/transcriptions", data=data, files={"file": ("audio.wav", wav, "audio/wav")})
                if r.status_code >= 500 or r.status_code == 429:
                    last = ASRError(f"HTTP {r.status_code}")
                    time.sleep(0.2 * (attempt + 1))
                    continue
                if r.status_code == 400 and "prompt" in data and attempt == 0:
                    data.pop("prompt")  # e.g. a prompt over the token limit: the speech matters more than the bias
                    continue
                if r.status_code >= 400:
                    raise ASRError(f"HTTP {r.status_code}: {_error_message(r)}")
                body = r.json()
                break
            except httpx.HTTPError as exc:
                last = ASRError(type(exc).__name__)
        else:
            raise last or ASRError("unknown")
        del wav
        segs = [
            Segment(
                text=(s.get("text") or "").strip(),
                no_speech_prob=float(s.get("no_speech_prob") or 0.0),
                avg_logprob=float(s.get("avg_logprob") or 0.0),
                compression_ratio=float(s.get("compression_ratio") or 1.0),
            )
            for s in body.get("segments") or []
        ]
        return ASRResult(text=(body.get("text") or "").strip(), segments=segs, model=self.name, ms=int((time.perf_counter() - t0) * 1000))

    def close(self) -> None:
        self._client.close()


def _error_message(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return r.text[:200]

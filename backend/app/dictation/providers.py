"""Model interfaces. ASR and LLM providers are swappable; the pipeline only knows these protocols."""

import time
from dataclasses import dataclass, field
from typing import Protocol

from app.config import settings
from app.logging import log


@dataclass
class Segment:
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 1.0


@dataclass
class ASRResult:
    text: str
    segments: list[Segment] = field(default_factory=list)
    model: str = ""
    ms: int = 0


class ASRError(Exception):
    pass


class ASRProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str, prompt: str, language: str | None) -> ASRResult: ...


class LLMProvider(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class GroqWhisper:
    """Whisper on Groq. temperature 0, language pinned, verbose segments for hallucination filtering."""

    def __init__(self, model: str, timeout_s: float = 8.0):
        self.name = model
        self.timeout_s = timeout_s

    async def transcribe(self, audio: bytes, filename: str, prompt: str, language: str | None) -> ASRResult:
        import groq

        t0 = time.perf_counter()
        try:
            client = groq.AsyncGroq(api_key=settings.groq_api_key, max_retries=0, timeout=self.timeout_s)
            res = await client.audio.transcriptions.create(
                file=(filename, audio),
                model=self.name,
                temperature=0,
                response_format="verbose_json",
                **({"language": language} if language else {}),
                **({"prompt": prompt} if prompt else {}),
            )
        except Exception as exc:  # timeouts, 5xx, connection errors: the pipeline falls back
            log.warning("dictation.asr_failed", model=self.name, error=type(exc).__name__)
            raise ASRError(type(exc).__name__) from exc
        raw_segments = getattr(res, "segments", None) or []
        segs = []
        for s in raw_segments:
            g = s if isinstance(s, dict) else s.__dict__
            segs.append(Segment(text=(g.get("text") or "").strip(), no_speech_prob=g.get("no_speech_prob") or 0.0, avg_logprob=g.get("avg_logprob") or 0.0, compression_ratio=g.get("compression_ratio") or 1.0))
        return ASRResult(text=(getattr(res, "text", "") or "").strip(), segments=segs, model=self.name, ms=int((time.perf_counter() - t0) * 1000))


def asr_chain() -> list[ASRProvider]:
    """Primary model, then a fallback model (the spec's local fallback isn't available on a web server)."""
    primary = settings.stt_model
    fallback = "whisper-large-v3" if primary != "whisper-large-v3" else "whisper-large-v3-turbo"
    return [GroqWhisper(primary, timeout_s=settings.stt_timeout_s), GroqWhisper(fallback, timeout_s=settings.stt_timeout_s * 2)]

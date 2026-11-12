"""The ASR interface. The pipeline only knows this protocol, so Groq, a local faster-whisper model (Phase 2) or a
test fake are interchangeable."""

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16_000


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
    """The provider failed (timeout, network, 4xx/5xx). The pipeline may fall back to another provider."""


class ASRProvider(Protocol):
    name: str

    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult:
        """`audio` is mono float32 at 16 kHz in [-1, 1]. `prompt` is a lexical bias (may be ""). `lang` is an ISO
        639-1 code, or None to let the model detect it."""
        ...

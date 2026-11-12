"""Silero VAD (the ONNX build bundled with faster-whisper, so no torch). Used to trim silence before ASR and to
paste nothing at all when there was no speech: Whisper invents text ("Thank you.") when given silence."""

from dataclasses import dataclass, fields
from typing import Protocol

import numpy as np

from flowtype.asr.base import SAMPLE_RATE


@dataclass
class Trimmed:
    audio: np.ndarray  # from just before the first speech to just after the last
    speech_ms: int  # total detected speech


class VAD(Protocol):
    def speech_spans(self, audio: np.ndarray) -> list[tuple[int, int]]:
        """(start, end) sample offsets of detected speech."""
        ...


class SileroVAD:
    def __init__(self, threshold: float = 0.5, min_silence_ms: int = 300):
        from faster_whisper.vad import VadOptions, get_speech_timestamps  # loads the ONNX model once

        self._get = get_speech_timestamps
        wanted = {"threshold": threshold, "min_silence_duration_ms": min_silence_ms, "speech_pad_ms": 30, "min_speech_duration_ms": 60}
        known = {f.name for f in fields(VadOptions)}  # option names have shifted between faster-whisper releases
        self._opts = VadOptions(**{k: v for k, v in wanted.items() if k in known})
        # Warm the model so the first dictation isn't slow.
        self._get(np.zeros(SAMPLE_RATE // 2, np.float32), self._opts)

    def speech_spans(self, audio: np.ndarray) -> list[tuple[int, int]]:
        if len(audio) < 512:
            return []
        return [(int(s["start"]), int(s["end"])) for s in self._get(audio.astype(np.float32), self._opts)]


def trim(audio: np.ndarray, vad: VAD, min_speech_ms: int = 250, pad_ms: int = 200) -> Trimmed | None:
    """None when there isn't enough speech to be worth transcribing."""
    spans = vad.speech_spans(audio)
    speech = sum(e - s for s, e in spans)
    if not spans or speech * 1000 < min_speech_ms * SAMPLE_RATE:
        return None
    pad = int(pad_ms * SAMPLE_RATE / 1000)
    start, end = max(0, spans[0][0] - pad), min(len(audio), spans[-1][1] + pad)
    return Trimmed(audio=audio[start:end], speech_ms=int(speech * 1000 / SAMPLE_RATE))

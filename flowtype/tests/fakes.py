"""Shared test doubles."""

import numpy as np

from flowtype.asr.base import ASRResult, Segment
from flowtype.llm.base import LLMError

SR = 16000


class SpeechAt:
    """A VAD that reports speech wherever the signal is loud (contiguous loud runs become spans)."""

    def speech_spans(self, audio):
        loud = np.abs(audio) > 0.05
        if not loud.any():
            return []
        spans, start, quiet = [], None, 0
        for i in range(0, len(audio), 160):  # 10 ms frames
            frame_loud = loud[i : i + 160].any()
            if frame_loud and start is None:
                start = i
            if frame_loud:
                quiet = 0
            elif start is not None:
                quiet += 160
                if quiet >= 1600:  # 100 ms of quiet ends a span
                    spans.append((start, i - quiet + 160))
                    start, quiet = None, 0
        if start is not None:
            spans.append((start, len(audio)))
        return spans


def ok(text, model="fake-whisper"):
    return ASRResult(text=text, segments=[Segment(text, no_speech_prob=0.01, avg_logprob=-0.2)], model=model)


class FakeASR:
    def __init__(self, *results, name="fake-whisper"):
        self.name = name
        self.results = list(results)
        self.calls = []

    def transcribe(self, audio, prompt, lang):
        self.calls.append({"prompt": prompt, "lang": lang, "peak": float(np.max(np.abs(audio))) if len(audio) else 0.0, "n": len(audio)})
        r = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(r, Exception):
            raise r
        return r


class FakeLLM:
    name = "fake-llm"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, messages, *, max_tokens=512, temperature=0.0, timeout_s=None):
        self.calls.append(messages)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, Exception):
            raise out
        return out


class FakeInjector:
    def __init__(self, selection=""):
        self.pasted = []
        self.selection = selection

    def paste(self, text):
        self.pasted.append(text)
        return 3

    def copy_selection(self):
        return self.selection


def speech_audio(seconds=1.0, lead=0.5, tail=0.5):
    a = np.zeros(int((lead + seconds + tail) * SR), np.float32)
    a[int(lead * SR) : int((lead + seconds) * SR)] = 0.2 * np.sin(np.linspace(0, 2000, int(seconds * SR)))
    return a


__all__ = ["SpeechAt", "ok", "FakeASR", "FakeLLM", "FakeInjector", "speech_audio", "LLMError", "SR"]

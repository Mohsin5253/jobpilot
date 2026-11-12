"""Microphone capture: 16 kHz mono float32 via sounddevice.

The input stream stays open so a short ring buffer always holds the last ~400 ms. When the key goes down, that
pre-roll becomes the start of the recording, so the first syllable isn't clipped if you start speaking a moment
before pressing. When the key comes up, recording continues for the post-roll (250 ms) so the last word isn't cut.
Everything stays in memory; the pipeline drops the samples once they're transcribed."""

import math
import threading
from collections import deque

import numpy as np

from flowtype.asr.base import SAMPLE_RATE

BLOCK = 512  # 32 ms at 16 kHz


class Recorder:
    def __init__(self, preroll_ms: int = 400, postroll_ms: int = 250, device: str | int | None = None):
        self.postroll_samples = int(postroll_ms * SAMPLE_RATE / 1000)
        self.preroll_samples = int(preroll_ms * SAMPLE_RATE / 1000)
        self._ring: deque[np.ndarray] = deque(maxlen=max(1, math.ceil(self.preroll_samples / BLOCK)))
        self._capture: list[np.ndarray] | None = None
        self._post_left = 0
        self._stopping = False
        self._post_done = threading.Event()
        self._lock = threading.Lock()
        self._device = _parse_device(device)
        self._stream = None
        self.last_status = ""
        self.level = -60.0

    # --- stream -------------------------------------------------------------------------------------------------
    def open(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK, device=self._device, callback=self._callback
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, _time, status) -> None:  # runs on the audio thread: keep it tiny
        if status:
            self.last_status = str(status)
        block = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
        self.level = max(-60.0, 20 * math.log10(rms + 1e-9))  # dBFS, for the overlay's meter
        with self._lock:
            self._ring.append(block)
            if self._capture is None:
                return
            if self._stopping:
                if self._post_left <= 0:
                    return
                block = block[: self._post_left]
                self._post_left -= len(block)
                self._capture.append(block)
                if self._post_left <= 0:
                    self._post_done.set()
            else:
                self._capture.append(block)

    # --- control (called from the controller thread) -----------------------------------------------------------
    @property
    def recording(self) -> bool:
        return self._capture is not None

    def start(self) -> None:
        with self._lock:
            pre = np.concatenate(list(self._ring)) if self._ring else np.zeros(0, np.float32)
            self._capture = [pre[-self.preroll_samples :]] if self.preroll_samples else []
            self._stopping = False
            self._post_done.clear()

    def peek(self) -> np.ndarray:
        """A copy of the recording so far (for speculative chunking); empty when not recording."""
        with self._lock:
            chunks = list(self._capture or [])
        return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)

    def stop(self) -> np.ndarray:
        """Wait for the post-roll, then hand back the whole recording (pre-roll + speech + post-roll)."""
        with self._lock:
            if self._capture is None:
                return np.zeros(0, np.float32)
            self._stopping = True
            self._post_left = self.postroll_samples
            if self._post_left <= 0:
                self._post_done.set()
        # If the stream has died (mic unplugged) don't hang: take what we have.
        self._post_done.wait(timeout=self.postroll_samples / SAMPLE_RATE + 0.5)
        with self._lock:
            chunks, self._capture, self._stopping = self._capture or [], None, False
        return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)

    def cancel(self) -> None:
        with self._lock:
            self._capture, self._stopping = None, False


def _parse_device(device: str | int | None):
    if device in (None, ""):
        return None
    if isinstance(device, int) or str(device).isdigit():
        return int(device)
    return str(device)


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())

"""Small signal helpers: peak normalisation and in-memory WAV encoding (audio never touches the disk)."""

import io
import wave

import numpy as np

from flowtype.asr.base import SAMPLE_RATE


def peak_normalise(audio: np.ndarray, target_dbfs: float = -3.0, max_gain_db: float = 30.0) -> np.ndarray:
    """Scale so the loudest sample sits at `target_dbfs`. Gain is capped so near-silence isn't blown up into noise."""
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak <= 1e-9:
        return audio
    gain = min(10 ** (target_dbfs / 20) / peak, 10 ** (max_gain_db / 20))
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


def to_wav(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """16-bit PCM mono WAV bytes."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def read_wav(path: str) -> np.ndarray:
    """A PCM WAV file as mono float32 at 16 kHz (for `flowtype transcribe` and evals)."""
    with wave.open(path, "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: "<i2", 4: "<i4"}[width]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    x = (x - 128) / 128 if width == 1 else x / float(2 ** (8 * width - 1))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SAMPLE_RATE:
        t_new = np.arange(0, len(x) * SAMPLE_RATE / sr) * sr / SAMPLE_RATE
        x = np.interp(t_new, np.arange(len(x)), x).astype(np.float32)
    return x.astype(np.float32)


def duration_ms(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> int:
    return int(len(audio) * 1000 / sample_rate)

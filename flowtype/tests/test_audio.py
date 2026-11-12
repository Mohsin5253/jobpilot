import numpy as np

from flowtype.audio.dsp import peak_normalise, read_wav, to_wav
from flowtype.audio.recorder import BLOCK, Recorder


def test_peak_normalise_to_minus_3_dbfs():
    x = (0.1 * np.sin(np.linspace(0, 100, 16000))).astype(np.float32)
    y = peak_normalise(x, -3.0)
    assert abs(20 * np.log10(np.max(np.abs(y))) - (-3.0)) < 0.01


def test_gain_is_capped_for_near_silence():
    x = np.full(1000, 1e-4, np.float32)
    y = peak_normalise(x, -3.0, max_gain_db=30)
    assert np.max(np.abs(y)) <= 1e-4 * 10 ** 1.5 + 1e-9


def test_wav_round_trip(tmp_path):
    x = (0.5 * np.sin(np.linspace(0, 50, 8000))).astype(np.float32)
    p = tmp_path / "a.wav"
    p.write_bytes(to_wav(x))
    y = read_wav(str(p))
    assert len(y) == len(x) and np.max(np.abs(y - x)) < 1e-3


def feed(rec, value, n_blocks):
    for _ in range(n_blocks):
        rec._callback(np.full((BLOCK, 1), value, np.float32), BLOCK, None, None)


def test_recorder_keeps_preroll_and_exact_postroll():
    import threading

    rec = Recorder(preroll_ms=400, postroll_ms=250)
    feed(rec, 0.1, 40)  # before the key: only the last 400 ms are kept
    rec.start()
    feed(rec, 0.5, 10)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", rec.stop()))
    t.start()
    while not rec._stopping:
        pass
    feed(rec, 0.9, 20)
    t.join(2)
    a = out["a"]
    assert np.count_nonzero(a == np.float32(0.1)) == rec.preroll_samples  # 6400
    assert np.count_nonzero(a == np.float32(0.5)) == 10 * BLOCK
    assert np.count_nonzero(a == np.float32(0.9)) == rec.postroll_samples  # 4000
    assert not rec.recording


def test_recorder_cancel_discards():
    rec = Recorder()
    rec.start()
    feed(rec, 0.5, 5)
    rec.cancel()
    assert not rec.recording and len(rec.stop()) == 0

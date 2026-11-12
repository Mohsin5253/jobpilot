"""A synthetic eval set from the OS's text-to-speech (macOS `say` with the Indian-English voices; Windows SAPI via
PowerShell). It isn't a substitute for real recordings of your voice, but it gives repeatable clips with names, jargon,
numbers, Hinglish, and noise/silence clips that must produce nothing. All names are fictional."""

import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 16000
WORDS = ["Kavya Menon", "Arjun Iyer", "Priya Raghunathan", "Sardar Patel College", "Kubernetes", "PostgreSQL", "FastAPI", "Zeta Labs", "Razorpay", "getUserById"]
SENTENCES = [
    ("names_1", "Please send the deck to Kavya Menon before the standup tomorrow."),
    ("names_2", "Arjun Iyer will join the call from Sardar Patel College at four thirty."),
    ("names_3", "Priya Raghunathan approved the budget for Zeta Labs."),
    ("tech_1", "We moved the billing service to Kubernetes and the database to PostgreSQL."),
    ("tech_2", "The FastAPI endpoint calls getUserById and returns in forty milliseconds."),
    ("tech_3", "Razorpay webhooks failed twice last night, so I added a retry."),
    ("numbers_1", "The invoice is for twelve thousand five hundred rupees, due on the third of December."),
    ("numbers_2", "We grew from two hundred to eighteen hundred users in six weeks."),
    ("chat_1", "Running ten minutes late, start without me."),
    ("chat_2", "Can you review my pull request when you get a chance?"),
    ("email_1", "Hi team, the release is on Friday. Please finish testing by Thursday evening. Thanks, Kavya."),
    ("hinglish_1", "Kal ka meeting cancel ho gaya, so let's sync on Monday."),
    ("hinglish_2", "Main abhi office pahunch raha hoon, ten minutes mein call karta hoon."),
    ("long_1", "First, we cleaned the data and removed the duplicates. Second, we trained the model on three months of orders. "
               "Third, we deployed it behind FastAPI on Kubernetes, and the error rate dropped by thirty percent."),
]
CONTEXT = {
    "tech_1": {"app": "Code.exe", "before": "## Infra notes\nThe Zeta Labs billing service runs on Kubernetes."},
    "chat_1": {"app": "slack.exe"}, "chat_2": {"app": "slack.exe"},
    "email_1": {"app": "OUTLOOK.EXE"},
}


def _write(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def tts(text: str, out: Path, voice: str) -> None:
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "a.aiff"
            subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", str(aiff), str(out)], check=True)
    elif sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({SR}, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono); "
              f"$s.SetOutputToWaveFile('{out}', $f); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=text, text=True, check=True)
    else:
        raise SystemExit("synth needs macOS `say` or Windows SAPI")


def build(out: Path, voices: list[str] | None = None, seed: int = 0) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    voices = voices or (["Rishi", "Tara", "Aman"] if sys.platform == "darwin" else [""])
    n = 0
    for i, (name, text) in enumerate(SENTENCES):
        voice = voices[i % len(voices)]
        path = out / f"{name}.wav"
        tts(text, path, voice)
        with wave.open(str(path)) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        # Realistic framing: half a second of room noise either side, a little noise under the speech.
        pad = rng.normal(0, 0.002, int(0.5 * SR)).astype(np.float32)
        x = np.concatenate([pad, x + rng.normal(0, 0.002, len(x)).astype(np.float32), pad])
        _write(path, x)
        (out / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        n += 1
    noise = {
        "silence_1": rng.normal(0, 0.001, 2 * SR),
        "noise_room": rng.normal(0, 0.01, 3 * SR),
        "noise_hum": 0.05 * np.sin(2 * np.pi * 50 * np.arange(3 * SR) / SR) + rng.normal(0, 0.003, 3 * SR),
        "noise_keyboard": _clicks(rng, 3.0),
        "noise_breath": _breath(rng, 2.5),
    }
    for name, x in noise.items():
        _write(out / f"{name}.wav", x.astype(np.float32))
        (out / f"{name}.txt").write_text("", encoding="utf-8")
        n += 1
    lines = ["words = [" + ", ".join(f'"{w}"' for w in WORDS) + "]", ""]
    for name, c in CONTEXT.items():
        lines.append(f"[clips.{name}]")
        lines += [f"{k} = {json.dumps(v)}" for k, v in c.items()]
        lines.append("")
    (out / "dataset.toml").write_text("\n".join(lines), encoding="utf-8")
    return n


def _clicks(rng, seconds: float) -> np.ndarray:
    x = rng.normal(0, 0.002, int(seconds * SR))
    for t in rng.uniform(0.1, seconds - 0.1, 18):
        i = int(t * SR)
        x[i : i + 200] += rng.normal(0, 0.25, 200) * np.exp(-np.arange(200) / 30)
    return x


def _breath(rng, seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    env = np.sin(np.linspace(0, 3 * np.pi, n)) ** 2
    noise = np.convolve(rng.normal(0, 1, n), np.ones(8) / 8, mode="same")
    return 0.04 * env * noise


def available() -> bool:
    return (sys.platform == "darwin" and shutil.which("say") is not None) or sys.platform == "win32"

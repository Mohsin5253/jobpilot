"""The eval harness: run the real pipeline over a folder of recordings under one or more config variants and score
each one.

Dataset: `name.wav` + `name.txt` (the reference). A clip with an empty or missing .txt whose name starts with
"noise" or "silence" must produce nothing: anything pasted there is a hallucination. An optional `dataset.toml`
gives the dictionary (`words = [...]`) and per-clip context (`[clips.name] app = "slack.exe"`, `before = "..."`).

Variants (`variants.toml`): `[[variant]] name = "vad-0.4"` with `set = { "vad.threshold" = 0.4 }`. The first
variant is the baseline; every other one is compared with it clip by clip (paired bootstrap on WER).

Metrics: WER and CER (jiwer, case and punctuation ignored), term accuracy (dictionary terms in the reference that
appear correctly spelled), hallucinations on non-speech clips, dropped speech, LLM rejections, latency p50/p95.
ASR responses are cached in memory per (audio, prompt, model), so variants that only change later stages don't
spend the API rate limit again."""

import copy
import hashlib
import json
import random
import re
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import jiwer
import numpy as np

from flowtype.audio.dsp import read_wav
from flowtype.config import Config, _apply
from flowtype.context.focus import FocusInfo, FocusProbe


@dataclass
class Clip:
    name: str
    path: Path
    reference: str | None  # None = non-speech: must produce nothing
    app: str | None = None
    before: str = ""


@dataclass
class Variant:
    name: str
    overrides: dict = field(default_factory=dict)


@dataclass
class ClipResult:
    clip: str
    variant: str
    hypothesis: str
    status: str
    wer: float | None
    cer: float | None
    total_ms: int
    asr_ms: int | None
    llm_status: str | None
    terms_hit: int = 0
    terms_total: int = 0


_TRANSFORM = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(), jiwer.RemoveMultipleSpaces(), jiwer.Strip(), jiwer.ReduceToListOfListOfWords()])
_CHAR = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(), jiwer.RemoveMultipleSpaces(), jiwer.Strip(), jiwer.ReduceToListOfListOfChars()])


def score(reference: str, hypothesis: str) -> tuple[float, float]:
    if not reference.strip():
        return (0.0 if not hypothesis.strip() else 1.0), 0.0
    hyp = hypothesis if hypothesis.strip() else "∅"
    w = jiwer.wer(reference, hyp, reference_transform=_TRANSFORM, hypothesis_transform=_TRANSFORM)
    c = jiwer.cer(reference, hyp, reference_transform=_CHAR, hypothesis_transform=_CHAR)
    return float(w), float(c)


def load_dataset(folder: Path) -> tuple[list[Clip], list[str]]:
    meta = {}
    if (folder / "dataset.toml").exists():
        meta = tomllib.loads((folder / "dataset.toml").read_text(encoding="utf-8"))
    clips = []
    for wav in sorted(folder.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        ref = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
        non_speech = not ref and re.match(r"(noise|silence)", wav.stem)
        if not ref and not non_speech:
            continue
        m = meta.get("clips", {}).get(wav.stem, {})
        clips.append(Clip(wav.stem, wav, None if non_speech else ref, m.get("app"), m.get("before", "")))
    return clips, list(meta.get("words", []))


def load_variants(path: Path | None) -> list[Variant]:
    if path is None:
        return [Variant("baseline")]
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [Variant(v["name"], dict(v.get("set", {}))) for v in data.get("variant", [])] or [Variant("baseline")]


def apply_overrides(cfg: Config, overrides: dict) -> Config:
    cfg = copy.deepcopy(cfg)
    nested: dict = {}
    for dotted, value in overrides.items():
        section, key = dotted.split(".", 1)
        nested.setdefault(section, {})[key] = value
    _apply(cfg, nested, "")
    return cfg


class CachingASR:
    """In-memory cache of ASR responses keyed by audio, prompt, language and engine."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.cache: dict[str, object] = {}
        self.calls = 0

    def transcribe(self, audio, prompt, lang):
        key = hashlib.sha1(np.ascontiguousarray(audio).tobytes() + f"|{prompt}|{lang}|{self.inner.name}".encode()).hexdigest()
        if key not in self.cache:
            self.calls += 1
            self.cache[key] = self.inner.transcribe(audio, prompt, lang)
        return copy.deepcopy(self.cache[key])


class _Capture:
    def __init__(self):
        self.text = ""

    def paste(self, text: str) -> int:
        self.text = text
        return 0


def run(clips: list[Clip], variants: list[Variant], base_cfg: Config, make_pipeline, words: list[str] | None = None, progress=print) -> list[ClipResult]:
    """`make_pipeline(cfg, injector)` returns a Pipeline (the CLI builds a real one; tests pass fakes)."""
    results: list[ClipResult] = []
    for v in variants:
        cfg = apply_overrides(base_cfg, v.overrides)
        cfg.dictionary.words = list(dict.fromkeys([*cfg.dictionary.words, *(words or [])]))
        cfg.learn.enabled = False
        for clip in clips:
            cap = _Capture()
            pipe = make_pipeline(cfg, cap)
            info = FocusInfo(app=clip.app, before_text=clip.before, is_password=False)
            d = pipe.run(read_wav(str(clip.path)), "file", time.perf_counter(), FocusProbe(lambda info=info: info), focus_down=FocusProbe(lambda info=info: info))
            hyp = cap.text.strip()
            ref = clip.reference or ""
            w, c = score(ref, hyp) if clip.reference is not None else (None, None)
            terms = [t for t in (words or []) if t.lower() in ref.lower()]
            hit = sum(1 for t in terms if t in hyp)
            results.append(ClipResult(clip.name, v.name, hyp, d.status, w, c, d.total_ms or 0, d.asr_ms, d.llm_status, hit, len(terms)))
            progress(f"  {v.name:18} {clip.name:28} {d.status:10} " + (f"WER {w:5.1%}" if w is not None else ("HALLUCINATED: " + hyp[:40] if hyp else "ok (nothing)")))
    return results


def summarise(results: list[ClipResult]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in dict.fromkeys(r.variant for r in results):
        rs = [r for r in results if r.variant == name]
        speech = [r for r in rs if r.wer is not None]
        non = [r for r in rs if r.wer is None]
        lat = sorted(r.total_ms for r in rs if r.status == "pasted")
        terms_total = sum(r.terms_total for r in speech)
        out[name] = {
            "clips": len(rs),
            "wer": round(float(np.mean([r.wer for r in speech])), 4) if speech else None,
            "cer": round(float(np.mean([r.cer for r in speech])), 4) if speech else None,
            "term_accuracy": round(sum(r.terms_hit for r in speech) / terms_total, 3) if terms_total else None,
            "hallucinations": sum(1 for r in non if r.hypothesis),
            "non_speech_clips": len(non),
            "dropped_speech": sum(1 for r in speech if r.status != "pasted"),
            "llm_rejected": sum(1 for r in rs if r.llm_status == "rejected"),
            "p50_ms": float(np.percentile(lat, 50)) if lat else None,
            "p95_ms": float(np.percentile(lat, 95)) if lat else None,
        }
    return out


def paired_bootstrap(a: list[float], b: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean WER difference (b - a) and its 95% interval, resampling clips."""
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b)]
    if not diffs:
        return 0.0, 0.0, 0.0
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return sum(diffs) / len(diffs), means[int(0.025 * n)], means[int(0.975 * n) - 1]


def compare(results: list[ClipResult]) -> list[dict]:
    names = list(dict.fromkeys(r.variant for r in results))
    if len(names) < 2:
        return []
    by = {(r.variant, r.clip): r for r in results}
    base = names[0]
    clips = [r.clip for r in results if r.variant == base and r.wer is not None]
    rows = []
    for name in names[1:]:
        pairs = [(by[(base, c)].wer, by[(name, c)].wer) for c in clips if (name, c) in by and by[(name, c)].wer is not None]
        mean, lo, hi = paired_bootstrap([p[0] for p in pairs], [p[1] for p in pairs])
        verdict = "better" if hi < 0 else "worse" if lo > 0 else "no clear difference"
        rows.append({"variant": name, "vs": base, "wer_delta": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)], "verdict": verdict})
    return rows


def report_markdown(summary: dict, comparisons: list[dict]) -> str:
    cols = ["wer", "cer", "term_accuracy", "hallucinations", "dropped_speech", "llm_rejected", "p50_ms", "p95_ms"]
    lines = ["| variant | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for name, s in summary.items():
        cells = []
        for c in cols:
            v = s[c]
            cells.append("–" if v is None else f"{v:.1%}" if c in ("wer", "cer", "term_accuracy") else (f"{v}/{s['non_speech_clips']}" if c == "hallucinations" else f"{v:.0f}" if isinstance(v, float) else str(v)))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    if comparisons:
        lines += ["", "| variant | vs | WER Δ | 95% CI | verdict |", "|---|---|---|---|---|"]
        for c in comparisons:
            lines.append(f"| {c['variant']} | {c['vs']} | {c['wer_delta']:+.1%} | [{c['ci95'][0]:+.1%}, {c['ci95'][1]:+.1%}] | {c['verdict']} |")
    return "\n".join(lines)


def save(results: list[ClipResult], summary: dict, comparisons: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(json.dumps({"summary": summary, "comparisons": comparisons, "clips": [r.__dict__ for r in results]}, indent=2), encoding="utf-8")
    md = out_dir / f"{stamp}.md"
    md.write_text(report_markdown(summary, comparisons) + "\n", encoding="utf-8")
    return md

"""Command line: `python -m flowtype` runs the dictation app; the subcommands manage keys, words and diagnostics."""

import argparse
import getpass
import sys
import time
from pathlib import Path

from flowtype import config as config_mod


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="flowtype", description="Hold Right Ctrl, speak, release: the text appears at your cursor.")
    p.add_argument("--config", type=Path, help="path to config.toml (default: the data folder)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start dictation (the default)")
    k = sub.add_parser("set-key", help="store an API key in the OS keychain")
    k.add_argument("provider", nargs="?", default="groq")
    dk = sub.add_parser("delete-key", help="remove an API key from the keychain")
    dk.add_argument("provider", nargs="?", default="groq")
    sub.add_parser("devices", help="list microphones")
    st = sub.add_parser("stats", help="recent dictations and per-stage latency")
    st.add_argument("-n", type=int, default=10)
    w = sub.add_parser("words", help="the personal dictionary")
    w.add_argument("action", choices=["list", "add", "remove"])
    w.add_argument("terms", nargs="*")
    w.add_argument("--star", action="store_true", help="always keep these terms in the prompt")
    t = sub.add_parser("transcribe", help="run the pipeline on a WAV file and print the text (no paste)")
    t.add_argument("wav", type=Path)
    e = sub.add_parser("eval", help="WER and latency over a folder of name.wav + name.txt pairs")
    e.add_argument("folder", type=Path)
    sub.add_parser("where", help="print the data folder")
    sub.add_parser("fetch-tokenizer", help="download Whisper's tokenizer (2 MB) so prompt lengths are counted exactly")
    args = p.parse_args(argv)
    cfg = config_mod.load(args.config)

    if args.cmd in (None, "run"):
        from flowtype.pipeline.app import run

        run(cfg)
    elif args.cmd == "set-key":
        from flowtype.secrets import set_key

        value = getpass.getpass(f"{args.provider} API key (input hidden): ")
        if not value.strip():
            sys.exit("Nothing entered; keychain unchanged.")
        set_key(args.provider, value)
        print(f"Saved to the OS keychain as service 'flowtype', account '{args.provider}_api_key'.")
    elif args.cmd == "delete-key":
        from flowtype.secrets import delete_key

        delete_key(args.provider)
        print("Removed.")
    elif args.cmd == "devices":
        from flowtype.audio.recorder import list_devices

        print(list_devices())
    elif args.cmd == "stats":
        _stats(args.n)
    elif args.cmd == "words":
        _words(args.action, args.terms, args.star)
    elif args.cmd == "transcribe":
        _transcribe(cfg, args.wav)
    elif args.cmd == "eval":
        _eval(cfg, args.folder)
    elif args.cmd == "where":
        print(config_mod.data_dir())
    elif args.cmd == "fetch-tokenizer":
        from huggingface_hub import hf_hub_download

        from flowtype.asr.prompt import TOKENIZER_REPO

        print(hf_hub_download(TOKENIZER_REPO, "tokenizer.json"))


def _store():
    from flowtype.store.db import Store

    return Store(config_mod.data_dir() / "flowtype.db")


def _stats(n: int) -> None:
    store = _store()
    rows = store.recent(n)
    print(f"{'id':>5}  {'when (UTC)':19}  {'mode':9}  {'status':16}  {'total':>6}  {'asr':>5}  {'vad':>4}  {'inject':>6}  words")
    for r in rows:
        print(f"{r['id']:>5}  {r['created_at'][:19]:19}  {r['mode']:9}  {r['status']:16}  {r['total_ms'] or '':>6}  {r['asr_ms'] or '':>5}  {r['vad_ms'] or '':>4}  {r['inject_ms'] or '':>6}  {r['words'] or ''}")
    summary = store.latency_summary()
    if summary:
        print("\nlatency over recent pasted dictations (ms):")
        for stage, v in summary.items():
            print(f"  {stage:14} p50 {v['p50']:>7}  p95 {v['p95']:>7}  (n={v['n']})")


def _words(action: str, terms: list[str], star: bool) -> None:
    store = _store()
    if action == "list":
        for r in store.words():
            print(("★ " if r["starred"] else "  ") + r["term"] + (f"  ({r['uses']} fixes)" if r["uses"] else ""))
    elif action == "add":
        for term in terms:
            store.add_word(term, starred=star)
        print(f"Added {len(terms)}.")
    else:
        print(f"Removed {sum(store.remove_word(t) for t in terms)}.")


class _PrintInjector:
    def __init__(self):
        self.text = ""

    def paste(self, text: str) -> int:
        self.text = text
        return 0


def _offline_pipeline(cfg):
    from flowtype.pipeline.app import build_asr, build_vad
    from flowtype.pipeline.dictate import Pipeline
    from flowtype.store.db import Store

    inj = _PrintInjector()
    store = _store()
    # A file run must not count as a dictation in your stats; log into a throwaway in-memory table instead,
    # but read the dictionary from the real store.
    pipe = Pipeline(cfg, build_vad(cfg), build_asr(cfg), inj, Store(":memory:"))
    pipe.vocabulary = lambda: ([r["term"] for r in store.words() if not r["starred"]] + list(cfg.dictionary.words), [r["term"] for r in store.words() if r["starred"]])
    return pipe, inj


def _transcribe(cfg, wav: Path) -> None:
    from flowtype.audio.dsp import read_wav

    pipe, inj = _offline_pipeline(cfg)
    d = pipe.run(read_wav(str(wav)), "file", time.perf_counter())
    print(inj.text.strip() if d.status == "pasted" else f"[{d.status}] {d.error or d.guard_dropped or ''}")
    print(f"  vad {d.vad_ms} ms · asr {d.asr_ms} ms{' (+retry ' + str(d.asr_retry_ms) + ' ms)' if d.asr_retried else ''} · total {d.total_ms} ms", file=sys.stderr)


def _eval(cfg, folder: Path) -> None:
    from flowtype.audio.dsp import read_wav
    from flowtype.eval.wer import wer

    pipe, inj = _offline_pipeline(cfg)
    scores, lat = [], []
    for wav in sorted(folder.glob("*.wav")):
        ref_path = wav.with_suffix(".txt")
        if not ref_path.exists():
            continue
        inj.text = ""
        d = pipe.run(read_wav(str(wav)), "file", time.perf_counter())
        score = wer(ref_path.read_text(encoding="utf-8"), inj.text)
        scores.append(score)
        lat.append(d.total_ms or 0)
        print(f"{wav.name:30} WER {score:6.1%}  {d.total_ms:>5} ms  {d.status}")
    if scores:
        print(f"\n{len(scores)} files · mean WER {sum(scores) / len(scores):.1%} · median latency {sorted(lat)[len(lat) // 2]} ms")


if __name__ == "__main__":
    main()

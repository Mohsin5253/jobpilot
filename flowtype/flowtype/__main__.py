"""Command line: `python -m flowtype` runs the dictation app; the subcommands manage keys, words, snippets, history,
evals and diagnostics."""

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
    st = sub.add_parser("stats", help="recent dictations, per-stage latency and Edit Rate")
    st.add_argument("-n", type=int, default=10)
    w = sub.add_parser("words", help="the personal dictionary")
    w.add_argument("action", choices=["list", "add", "remove"])
    w.add_argument("terms", nargs="*")
    w.add_argument("--star", action="store_true", help="always keep these terms in the prompt")
    sn = sub.add_parser("snippets", help="spoken shortcuts: say the cue, get the expansion")
    sn.add_argument("action", choices=["list", "add", "remove"])
    sn.add_argument("cue", nargs="?")
    sn.add_argument("expansion", nargs="?")
    h = sub.add_parser("history", help="what you dictated (needs store_text = true)")
    h.add_argument("-n", type=int, default=20)
    h.add_argument("--search", default="")
    h.add_argument("--copy", type=int, metavar="ID", help="copy one entry to the clipboard")
    h.add_argument("--erase", action="store_true", help="erase all stored text")
    t = sub.add_parser("transcribe", help="run the pipeline on a WAV file and print the text (no paste)")
    t.add_argument("wav", type=Path)
    t.add_argument("--app", help="pretend this app has focus (picks the clean-up style)")
    e = sub.add_parser("eval", help="score the pipeline on a folder of recordings, optionally A/B over config variants")
    e.add_argument("folder", type=Path)
    e.add_argument("--variants", type=Path, help="variants.toml ([[variant]] name=..., set={...})")
    e.add_argument("--out", type=Path, help="report folder (default: <folder>/reports)")
    e.add_argument("--pace", type=float, default=0.0, help="seconds to wait between clips (API rate limits)")
    sy = sub.add_parser("synth", help="build a synthetic eval set with the OS's text-to-speech")
    sy.add_argument("folder", type=Path)
    db = sub.add_parser("debug", help="open the debug panel (local web page)")
    db.add_argument("--port", type=int)
    db.add_argument("--no-browser", action="store_true")
    au = sub.add_parser("autostart", help="start Flowtype when you log in")
    au.add_argument("action", choices=["enable", "disable", "status"])
    sub.add_parser("fetch-tokenizer", help="download Whisper's tokenizer (2 MB) so prompt lengths are counted exactly")
    fm = sub.add_parser("fetch-model", help="download the local fallback Whisper model")
    fm.add_argument("--size", help="tiny, base, small (default), medium, large-v3")
    sub.add_parser("where", help="print the data folder")
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
    elif args.cmd == "snippets":
        _snippets(args.action, args.cue, args.expansion)
    elif args.cmd == "history":
        _history(cfg, args)
    elif args.cmd == "transcribe":
        _transcribe(cfg, args.wav, args.app)
    elif args.cmd == "eval":
        _eval(cfg, args.folder, args.variants, args.out, args.pace)
    elif args.cmd == "synth":
        from flowtype.eval.synth import build

        print(f"Wrote {build(args.folder)} clips to {args.folder}")
    elif args.cmd == "debug":
        _debug(cfg, args.port, not args.no_browser)
    elif args.cmd == "autostart":
        from flowtype import autostart

        if args.action == "enable":
            print("Enabled:", autostart.enable())
        elif args.action == "disable":
            print("Disabled." if autostart.disable() else "It wasn't enabled.")
        else:
            print(autostart.status() or "Not enabled.")
    elif args.cmd == "where":
        print(config_mod.data_dir())
    elif args.cmd == "fetch-tokenizer":
        from huggingface_hub import hf_hub_download

        from flowtype.asr.prompt import TOKENIZER_REPO

        print(hf_hub_download(TOKENIZER_REPO, "tokenizer.json"))
    elif args.cmd == "fetch-model":
        from flowtype.asr.local_whisper import LocalWhisper

        size = args.size or cfg.asr.local_model
        LocalWhisper(size).load()
        print(f"Local model '{size}' is ready.")


def _store():
    from flowtype.store.db import Store

    return Store(config_mod.data_dir() / "flowtype.db")


def _stats(n: int) -> None:
    store = _store()
    rows = store.recent(n)
    print(f"{'id':>5}  {'when (UTC)':19}  {'mode':9}  {'status':16}  {'style':8}  {'total':>6}  {'asr':>5}  {'llm':>5}  {'inject':>6}  words")
    for r in rows:
        print(f"{r['id']:>5}  {r['created_at'][:19]:19}  {r['mode']:9}  {r['status']:16}  {r['style'] or '':8}  {r['total_ms'] or '':>6}  {r['asr_ms'] or '':>5}  {r['llm_ms'] or '':>5}  {r['inject_ms'] or '':>6}  {r['words'] or ''}")
    summary = store.latency_summary()
    if summary:
        print("\nlatency over recent pasted dictations (ms):")
        for stage, v in summary.items():
            print(f"  {stage:14} p50 {v['p50']:>7}  p95 {v['p95']:>7}  (n={v['n']})")
    er = store.edit_rate_summary()
    if er:
        print("\nEdit Rate (how much you changed after pasting):")
        for k, v in er.items():
            print(f"  {k:14} {v['edit_rate']:.1%}  (n={v['n']})")


def _words(action: str, terms: list[str], star: bool) -> None:
    store = _store()
    if action == "list":
        for r in store.words():
            print(("★ " if r["starred"] else "  ") + r["term"] + (" (learned)" if r["source"] == "learned" else "") + (f"  ({r['uses']} fixes)" if r["uses"] else ""))
    elif action == "add":
        for term in terms:
            store.add_word(term, starred=star)
        print(f"Added {len(terms)}.")
    else:
        print(f"Removed {sum(store.remove_word(t) for t in terms)}.")


def _snippets(action: str, cue: str | None, expansion: str | None) -> None:
    store = _store()
    if action == "list":
        for c, x in store.snippets():
            print(f"{c!r:30} -> {x}")
    elif action == "add":
        if not cue or expansion is None:
            sys.exit('Usage: flowtype snippets add "my email address" "kavya@example.com"')
        store.add_snippet(cue, expansion)
        print("Added.")
    else:
        print("Removed." if cue and store.remove_snippet(cue) else "No such snippet.")


def _history(cfg, args) -> None:
    store = _store()
    if args.erase:
        print(f"Erased the text of {store.erase_all_text()} dictations.")
        return
    if args.copy is not None:
        row = store.get(args.copy)
        if not row or not row["text"]:
            sys.exit("No stored text for that id.")
        from flowtype.inject.clipboard import default_backend

        default_backend().set_text(row["text"])
        print("Copied.")
        return
    rows = store.history(args.n, args.search)
    if not rows:
        print("No history." + ("" if cfg.store.store_text else " Text isn't stored: set store_text = true in config.toml to keep it."))
    for r in rows:
        print(f"{r['id']:>5}  {r['created_at'][:16]}  {r['app'] or '':16}  {r['text']}")


class _PrintInjector:
    def __init__(self):
        self.text = ""

    def paste(self, text: str) -> int:
        self.text = text
        return 0


def _make_pipeline_factory(cfg):
    """A factory that builds pipelines sharing one VAD, one ASR (cached) and one LLM, reading the real dictionary."""
    from flowtype.eval.harness import CachingASR
    from flowtype.pipeline.app import build_asr, build_llm, build_vad
    from flowtype.pipeline.dictate import Pipeline
    from flowtype.store.db import Store

    real = _store()
    vad = build_vad(cfg)
    cache: dict = {}

    def factory(c, injector):
        key = (c.asr.mode, c.asr.model, c.asr.fallback, c.asr.second_model, c.llm.enabled, c.llm.model)
        if key not in cache:
            asr, _p, _l = build_asr(c)
            cache[key] = (CachingASR(asr), build_llm(c))
        asr, llm = cache[key]
        mem = Store(":memory:")  # file runs don't count as dictations in your stats
        for r in real.words():
            mem.add_word(r["term"], bool(r["starred"]), r["source"])
        for cue, x in real.snippets():
            mem.add_snippet(cue, x)
        return Pipeline(c, vad, asr, injector, mem, llm=llm)

    return factory


def _transcribe(cfg, wav: Path, app: str | None) -> None:
    from flowtype.audio.dsp import read_wav
    from flowtype.context.focus import FocusInfo, FocusProbe

    inj = _PrintInjector()
    pipe = _make_pipeline_factory(cfg)(cfg, inj)
    info = FocusInfo(app=app, is_password=False)
    d = pipe.run(read_wav(str(wav)), "file", time.perf_counter(), FocusProbe(lambda: info), focus_down=FocusProbe(lambda: info))
    print(inj.text.strip() if d.status == "pasted" else f"[{d.status}] {d.error or d.guard_dropped or ''}")
    print(f"  style {d.style} · vad {d.vad_ms} ms · asr {d.asr_ms} ms{' (+retry)' if d.asr_retried else ''} · clean-up {d.llm_status} {d.llm_ms or ''} ms"
          f"{' (' + d.llm_reason + ')' if d.llm_reason else ''} · total {d.total_ms} ms", file=sys.stderr)


def _eval(cfg, folder: Path, variants_path: Path | None, out: Path | None, pace: float = 0.0) -> None:
    from flowtype.eval import harness

    clips, words = harness.load_dataset(folder)
    if not clips:
        sys.exit(f"No clips in {folder} (need name.wav + name.txt pairs)")
    variants = harness.load_variants(variants_path)
    print(f"{len(clips)} clips × {len(variants)} variants")
    results = harness.run(clips, variants, cfg, _make_pipeline_factory(cfg), words, pace_s=pace)
    summary, comparisons = harness.summarise(results), harness.compare(results)
    print("\n" + harness.report_markdown(summary, comparisons))
    print(f"\nReport: {harness.save(results, summary, comparisons, out or folder / 'reports')}")


def _debug(cfg, port: int | None, browser: bool) -> None:
    from flowtype.ui.debug_server import serve

    port = port or cfg.ui.debug_port
    url = f"http://127.0.0.1:{port}/"
    print(f"Debug panel at {url} (Ctrl+C to stop)")
    if browser:
        import webbrowser

        webbrowser.open(url)
    try:
        serve(_store(), port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

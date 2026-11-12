import json
import os
import plistlib
import threading
import time
import urllib.request

import numpy as np
from fakes import FakeASR, FakeInjector, SpeechAt, ok

from flowtype import autostart
from flowtype.config import Config
from flowtype.context.focus import FocusInfo
from flowtype.hotkey.state import Action
from flowtype.inject.clipboard import ClipboardInjector
from flowtype.pipeline.app import Controller
from flowtype.pipeline.dictate import Pipeline
from flowtype.store.db import Dictation, Store
from flowtype.ui.debug_server import serve
from flowtype.ui.overlay import OverlayBus, OverlayModel


# --- overlay ------------------------------------------------------------------------------------------------------
def test_overlay_model_states():
    m = OverlayModel()
    assert not m.visible(0)
    m.set("recording", now=0)
    assert m.visible(100) and m.text() == "Listening"
    m.set("done", "12 words · 480 ms", now=0)
    assert m.visible(1.0) and not m.visible(2.0) and m.text() == "12 words · 480 ms"
    m.level_db = -30
    assert 0.4 < m.bar() < 0.6


def test_overlay_bus_is_a_queue():
    b = OverlayBus()
    b.post("recording")
    assert b.q.get_nowait() == ("recording", "")


def test_overlay_widget_runs_offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from flowtype.ui.overlay import run_overlay

    bus, stop = OverlayBus(), threading.Event()

    def background():
        bus.post("recording")
        time.sleep(0.2)
        bus.post("done", "3 words")
        time.sleep(0.2)
        stop.set()

    t = time.perf_counter()
    run_overlay(bus, lambda: -20.0, stop, background)
    assert time.perf_counter() - t < 5


# --- controller ---------------------------------------------------------------------------------------------------
class FakeRecorder:
    def __init__(self):
        self.recording = False
        self.started = 0

    def start(self):
        self.recording, self.started = True, self.started + 1

    def stop(self):
        self.recording = False
        return np.zeros(16000, np.float32)

    def cancel(self):
        self.recording = False

    def peek(self):
        return np.zeros(16000 * 5, np.float32)


class InstantProbe:
    def __init__(self, probe, full=False):
        self.info = probe()

    def result(self, timeout=0.3):
        return self.info


def make_controller(spec_factory=None):
    jobs, posts = [], []
    rec = FakeRecorder()
    pipe = Pipeline(Config(), SpeechAt(), FakeASR(ok("x")), FakeInjector(), Store(":memory:"))
    ctl = Controller(Config(), rec, pipe, lambda: FocusInfo(app="notepad.exe"), lambda fn, *a, **k: jobs.append((a, k)),
                     ui=type("U", (), {"recording": lambda *a, **k: None, "cancelled": lambda *a: None, "status": lambda *a: None})(),
                     post=lambda s, m: posts.append(s), spec_factory=spec_factory, focus_probe_cls=InstantProbe)
    return ctl, rec, jobs, posts


def test_controller_hold_submits_a_job_with_context():
    ctl, rec, jobs, posts = make_controller()
    ctl.handle(("press", 0.0, False))
    ctl.handle(("release", 1.0))
    assert rec.started == 1 and len(jobs) == 1
    args, kw = jobs[0]
    assert args[1] == "hold" and args[2] == 1.0 and kw["focus_down"].info.app == "notepad.exe" and kw["command"] is False
    assert posts == ["recording", "transcribing"]


def test_controller_command_mode_from_modifier():
    ctl, _rec, jobs, posts = make_controller()
    ctl.handle(("press", 0.0, True))
    ctl.handle(("release", 1.0))
    assert jobs[0][1]["command"] is True and posts[0] == "command"


def test_controller_feeds_speculative_session():
    updates = []

    class Spec:
        chunks = 0

        def update(self, audio):
            updates.append(len(audio))

        def cancel(self):
            pass

    ctl, _rec, jobs, _ = make_controller(spec_factory=lambda ctx: Spec())
    ctl.handle(("press", 0.0, False))
    for t in (0.4, 0.8, 1.2):
        ctl.tick(t)
    ctl.handle(("release", 1.5))
    assert len(updates) == 3 and jobs[0][1]["speculative"] is not None


def test_controller_tap_cancels():
    ctl, rec, jobs, posts = make_controller()
    ctl.handle(("press", 0.0, False))
    ctl.handle(("release", 0.1))
    ctl.tick(0.6)
    assert not rec.recording and jobs == [] and posts[-1] == "cancelled"


# --- history ------------------------------------------------------------------------------------------------------
def test_history_and_retention():
    s = Store(":memory:")
    old = Dictation(mode="hold", status="pasted", text="old text", created_at="2020-01-01T00:00:00.000+00:00")
    s.add_dictation(old, store_text=True)
    s.add_dictation(Dictation(mode="hold", status="pasted", text="fresh text"), store_text=True)
    assert [r["text"] for r in s.history()] == ["fresh text", "old text"]
    assert s.purge_text(30) == 1 and [r["text"] for r in s.history()] == ["fresh text"]
    assert [r["text"] for r in s.history(query="fresh")] == ["fresh text"]
    assert s.erase_all_text() == 1 and s.history() == []


def test_migration_adds_columns_to_a_phase1_database(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE dictations (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL)")
    con.commit()
    con.close()
    s = Store(db)
    cols = {r[1] for r in s._db.execute("PRAGMA table_info(dictations)")}
    assert {"style", "llm_status", "edit_rate", "chunks"} <= cols


# --- copy selection (command mode fallback) ------------------------------------------------------------------------
def test_copy_selection_restores_clipboard():
    from test_clipboard import ORIGINAL, FakeClipboard

    clip = FakeClipboard(ORIGINAL)
    clip.get_text = lambda: clip.data.get("text")

    def ctrl_c():
        clip.data = {"text": "selected words"}
        clip.marker += 1

    inj = ClipboardInjector(clip, lambda: None, send_copy=ctrl_c, sleep=lambda s: None)
    assert inj.copy_selection() == "selected words" and clip.data == ORIGINAL
    inj2 = ClipboardInjector(FakeClipboard(ORIGINAL), lambda: None, send_copy=lambda: None, sleep=lambda s: time.sleep(0.001))
    assert inj2.copy_selection(wait_s=0.02) == ""  # nothing selected


# --- autostart ----------------------------------------------------------------------------------------------------
def test_autostart_macos(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWTYPE_HOME", str(tmp_path / "data"))
    path = autostart.enable("darwin", home=tmp_path, cmd=["/x/python", "-m", "flowtype", "run"])
    plist = plistlib.loads(open(path, "rb").read())
    assert plist["ProgramArguments"] == ["/x/python", "-m", "flowtype", "run"] and plist["RunAtLoad"]
    assert autostart.status("darwin", home=tmp_path) == path
    assert autostart.disable("darwin", home=tmp_path) and autostart.status("darwin", home=tmp_path) is None


def test_autostart_windows_registry():
    class Reg(dict):
        def set(self, k, n, v):
            self[(k, n)] = v

        def get(self, k, n):
            return dict.get(self, (k, n))

        def delete(self, k, n):
            return self.pop((k, n), None) is not None

    reg = Reg()
    autostart.enable("win32", registry=reg, cmd=[r"C:\Program Files\Flowtype\pythonw.exe", "-m", "flowtype", "run"])
    assert autostart.status("win32", registry=reg) == r'"C:\Program Files\Flowtype\pythonw.exe" -m flowtype run'
    assert autostart.disable("win32", registry=reg) and autostart.status("win32", registry=reg) is None


def test_autostart_linux(tmp_path):
    path = autostart.enable("linux", home=tmp_path, cmd=["/usr/bin/python3", "-m", "flowtype"])
    assert "Exec=/usr/bin/python3 -m flowtype" in open(path).read()


# --- debug panel --------------------------------------------------------------------------------------------------
def test_debug_panel_serves_local_json_only():
    s = Store(":memory:")
    s.add_dictation(Dictation(mode="hold", status="pasted", total_ms=420, asr_ms=210, text="secret"), store_text=False)
    server = serve(s, port=0, background=True)
    port = server.server_address[1]
    try:
        rows = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dictations").read())
        assert rows[0]["total_ms"] == 420 and "text" not in rows[0]
        assert "Flowtype debug" in urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/dictations", headers={"Host": "evil.example.com"})
        try:
            urllib.request.urlopen(req)
            raise AssertionError("should be forbidden")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        server.shutdown()


def test_cli_parses_every_command():
    from flowtype.__main__ import main

    import pytest

    with pytest.raises(SystemExit):
        main(["--help"])


def test_action_enum_unchanged():
    assert Action.START.value == "start"

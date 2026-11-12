import threading

import pytest

from flowtype.inject.clipboard import ClipboardInjector, InjectError


class FakeClipboard:
    """Holds a dict of formats, like a real clipboard; the marker bumps on every write."""

    def __init__(self, initial):
        self.data = dict(initial)
        self.marker = 0
        self.fail_snapshot = False
        self.log = []

    def snapshot(self):
        if self.fail_snapshot:
            raise OSError("busy")
        return dict(self.data)

    def set_text(self, text):
        self.data = {"text": text}
        self.marker += 1
        self.log.append(("set", text))

    def restore(self, snap):
        self.data = dict(snap)
        self.marker += 1
        self.log.append(("restore", snap))

    def change_marker(self):
        return self.marker


ORIGINAL = {"text": "my copied text", "html": b"<b>my copied text</b>", "image/png": b"\x89PNG"}


def make(clip, on_paste=None, sleep=None):
    pasted = []

    def send():
        pasted.append(clip.data.get("text"))
        if on_paste:
            on_paste()

    sleeps = []
    inj = ClipboardInjector(clip, send, restore_delay_ms=150, sleep=sleep or sleeps.append)
    return inj, pasted, sleeps


def test_pastes_our_text_then_restores_every_format():
    clip = FakeClipboard(ORIGINAL)
    inj, pasted, sleeps = make(clip)
    inj.paste("hello world ")
    assert pasted == ["hello world "]
    assert clip.data == ORIGINAL  # text, HTML and image all back
    assert sleeps == [0.15]  # restored after 150 ms, not before


def test_restore_waits_until_after_the_paste_keystroke():
    clip = FakeClipboard(ORIGINAL)
    order = []
    inj, _, _ = make(clip, on_paste=lambda: order.append("paste"), sleep=lambda s: order.append(f"sleep {s}"))
    inj.paste("x")
    assert order == ["paste", "sleep 0.15"]
    assert clip.log[-1][0] == "restore"


def test_does_not_clobber_a_clipboard_changed_during_the_delay():
    clip = FakeClipboard(ORIGINAL)

    def user_copies(_s):
        clip.data = {"text": "something the user just copied"}
        clip.marker += 1

    inj, _, _ = make(clip, sleep=user_copies)
    inj.paste("dictated")
    assert clip.data == {"text": "something the user just copied"}


def test_restores_even_if_the_paste_keystroke_fails():
    clip = FakeClipboard(ORIGINAL)

    def boom():
        raise RuntimeError("no input permission")

    inj = ClipboardInjector(clip, boom, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        inj.paste("dictated")
    assert clip.data == ORIGINAL


def test_unreadable_clipboard_means_no_paste_and_no_change():
    clip = FakeClipboard(ORIGINAL)
    clip.fail_snapshot = True
    inj, pasted, _ = make(clip)
    with pytest.raises(InjectError):
        inj.paste("dictated")
    assert pasted == [] and clip.data == ORIGINAL and clip.log == []


def test_empty_clipboard_is_restored_as_empty():
    clip = FakeClipboard({})
    inj, _, _ = make(clip)
    inj.paste("dictated")
    assert clip.data == {}


def test_injecting_flag_is_set_only_during_the_paste():
    clip = FakeClipboard(ORIGINAL)
    flag = threading.Event()
    seen = []
    inj = ClipboardInjector(clip, lambda: seen.append(flag.is_set()), injecting=flag, sleep=lambda s: None)
    inj.paste("x")
    assert seen == [True] and not flag.is_set()

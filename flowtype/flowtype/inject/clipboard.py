"""Paste at the cursor through the clipboard: save what's on it, put the text there, press Ctrl+V (Cmd+V on macOS),
then put the original back 150 ms later. Typing the text key by key would be slower and breaks on IMEs and
non-ASCII; the clipboard works in every app that accepts paste.

The original is restored only if the clipboard still holds our text: if something else (you, or a clipboard tool)
changed it in those 150 ms, we leave it alone. Our text is marked so Windows clipboard history, cloud clipboard and
macOS clipboard managers skip it."""

import sys
import threading
import time
from typing import Any, Callable, Protocol


class InjectError(Exception):
    pass


class ClipboardBackend(Protocol):
    def snapshot(self) -> Any:
        """Everything on the clipboard now, in a form `restore` can put back."""
        ...

    def set_text(self, text: str) -> None: ...

    def restore(self, snap: Any) -> None: ...

    def change_marker(self) -> int:
        """A number that changes whenever the clipboard's contents change."""
        ...


class ClipboardInjector:
    def __init__(
        self,
        backend: ClipboardBackend,
        send_paste: Callable[[], None],
        restore_delay_ms: int = 150,
        injecting: threading.Event | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.backend = backend
        self.send_paste = send_paste
        self.restore_delay_s = restore_delay_ms / 1000
        self.injecting = injecting or threading.Event()
        self.sleep = sleep

    def paste(self, text: str) -> int:
        """Paste `text`; returns ms from start until the paste keystroke was sent (the restore happens after)."""
        t0 = time.perf_counter()
        try:
            snap = self.backend.snapshot()
        except Exception as exc:  # unreadable clipboard: don't paste, or we'd destroy what's on it
            raise InjectError(f"could not read the clipboard: {exc}") from exc
        try:
            self.backend.set_text(text)
        except Exception as exc:
            raise InjectError(f"could not set the clipboard: {exc}") from exc
        ours = self.backend.change_marker()
        sent_ms = 0
        try:
            self.injecting.set()
            self.send_paste()
            sent_ms = int((time.perf_counter() - t0) * 1000)
            self.sleep(self.restore_delay_s)
        finally:
            self.injecting.clear()
            if self.backend.change_marker() == ours:
                self.backend.restore(snap)
        return sent_ms


# --- paste keystroke ----------------------------------------------------------------------------------------------
def make_send_paste() -> Callable[[], None]:
    from pynput.keyboard import Controller, Key, KeyCode

    kb = Controller()
    if sys.platform == "darwin":
        mod, v = Key.cmd, KeyCode.from_char("v")
    elif sys.platform == "win32":
        mod, v = Key.ctrl, KeyCode.from_vk(0x56)  # VK_V: works whatever the keyboard layout
    else:
        mod, v = Key.ctrl, KeyCode.from_char("v")

    def send() -> None:
        with kb.pressed(mod):
            kb.press(v)
            kb.release(v)
        time.sleep(0.01)

    return send


def default_backend() -> ClipboardBackend:
    if sys.platform == "win32":
        from flowtype.inject.win_clipboard import WinClipboard

        return WinClipboard()
    if sys.platform == "darwin":
        from flowtype.inject.mac_clipboard import MacClipboard

        return MacClipboard()
    return TextOnlyClipboard()


class TextOnlyClipboard:
    """Linux fallback via pyperclip: only text survives the round trip."""

    def __init__(self):
        import pyperclip

        self._pc = pyperclip
        self._n = 0
        self._last = None

    def snapshot(self):
        return self._pc.paste()

    def set_text(self, text: str) -> None:
        self._pc.copy(text)

    def restore(self, snap) -> None:
        self._pc.copy(snap or "")

    def change_marker(self) -> int:
        cur = self._pc.paste()
        if cur != self._last:
            self._last, self._n = cur, self._n + 1
        return self._n

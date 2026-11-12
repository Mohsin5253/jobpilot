"""The global keyboard hook (pynput). Callbacks run on the OS hook thread, and on Windows a slow low-level hook
delays every keystroke system-wide, so they only timestamp the event and queue it; the controller does the rest."""

import queue
import threading
import time


def resolve_key(name: str):
    from pynput.keyboard import Key, KeyCode

    if hasattr(Key, name):
        return getattr(Key, name)
    if len(name) == 1:
        return KeyCode.from_char(name)
    raise ValueError(f"Unknown hotkey {name!r}: use a pynput Key name such as ctrl_r, alt_r, cmd_r or f13")


class HotkeyListener:
    def __init__(self, key_name: str, events: "queue.Queue[tuple]", injecting: threading.Event, command_modifier: str = "shift"):
        from pynput import keyboard

        self._kb = keyboard
        self._key = resolve_key(key_name)
        K = keyboard.Key
        self._mods = {"shift": {K.shift, K.shift_l, K.shift_r}, "alt": {K.alt, K.alt_l, K.alt_r}, "none": set()}.get(command_modifier, {K.shift, K.shift_l, K.shift_r})
        self._mods.discard(self._key)
        self._mods_down: set = set()
        self._events = events
        self._injecting = injecting  # our own Ctrl+V must not look like the user pressing a shortcut
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)

    @property
    def trusted(self) -> bool:
        """macOS only: False when the app lacks Input Monitoring / Accessibility permission."""
        return getattr(self._listener, "IS_TRUSTED", True)

    def start(self) -> None:
        self._listener.start()
        self._listener.wait()

    def stop(self) -> None:
        self._listener.stop()

    def _on_press(self, key) -> None:
        now = time.perf_counter()
        if key == self._key:
            self._events.put(("press", now, bool(self._mods_down)))
        elif key in self._mods:
            self._mods_down.add(key)  # a modifier held before the hotkey selects command mode; it isn't a shortcut
        elif not self._injecting.is_set():
            self._events.put(("other", now, key == self._kb.Key.esc))

    def _on_release(self, key) -> None:
        if key == self._key:
            self._events.put(("release", time.perf_counter()))
        self._mods_down.discard(key)

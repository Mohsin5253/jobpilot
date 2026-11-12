"""The overlay: a small pill at the bottom of the screen that shows what Flowtype is doing (recording with a level
meter, hands-free, command mode, transcribing, done, error). It never takes focus, so the text still lands in the
app you were typing in.

`OverlayModel` is the state (pure, testable); `Overlay` paints it with PySide6 and polls a queue every 33 ms, so
other threads never touch Qt objects."""

import queue
import sys
import time
from dataclasses import dataclass

FLASH_S = {"done": 1.4, "error": 3.0}
LABELS = {
    "recording": "Listening", "handsfree": "Hands-free · tap to stop", "command": "Command · say an instruction",
    "transcribing": "Transcribing…", "done": "", "error": "", "cancelled": "Cancelled", "idle": "",
}


@dataclass
class OverlayModel:
    state: str = "idle"
    message: str = ""
    since: float = 0.0
    level_db: float = -60.0

    def set(self, state: str, message: str = "", now: float | None = None) -> None:
        self.state, self.message, self.since = state, message, time.monotonic() if now is None else now

    def text(self) -> str:
        return self.message or LABELS.get(self.state, "")

    def visible(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.state == "idle":
            return False
        if self.state in FLASH_S or self.state == "cancelled":
            return now - self.since < FLASH_S.get(self.state, 0.8)
        return True

    def bar(self) -> float:
        """0..1 meter height from the input level (-50 dBFS .. -10 dBFS)."""
        return max(0.0, min(1.0, (self.level_db + 50) / 40))


class OverlayBus:
    """Thread-safe: any thread may call `post`; the Qt side drains it."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()

    def post(self, state: str, message: str = "") -> None:
        self.q.put((state, message))


def run_overlay(bus: OverlayBus, level_fn, stop_event, background) -> None:
    """Run the Qt event loop on this (main) thread, `background()` on another; returns when stop_event is set."""
    import signal
    import threading

    from PySide6.QtCore import QRect, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    COLORS = {"recording": "#e5484d", "handsfree": "#e5484d", "command": "#8e4ec6", "transcribing": "#3e63dd", "done": "#30a46c", "error": "#f76b15", "cancelled": "#8b8d98"}

    class Overlay(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            # macOS hides tool windows whenever their app isn't active, and Flowtype is never the active app
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
            self.model = OverlayModel()
            self.resize(300, 44)
            _no_activate(self)  # before the first show: a window joins its Spaces when it's first ordered in
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.timer.start(33)

        def place(self):
            screen = QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.bottom() - self.height() - 48)

        def poll(self):
            if stop_event.is_set():
                QApplication.quit()
                return
            changed = False
            while True:
                try:
                    st, msg = bus.q.get_nowait()
                except queue.Empty:
                    break
                self.model.set(st, msg)
                changed = True
            if self.model.state in ("recording", "handsfree", "command"):
                self.model.level_db = level_fn()
                changed = True
            vis = self.model.visible()
            if vis and not self.isVisible():
                self.place()
                self.show()
                _no_activate(self)
            elif not vis and self.isVisible():
                self.hide()
            if changed:
                self.update()

        def paintEvent(self, _e):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(24, 24, 27, 235))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), 22, 22)
            p.setBrush(QColor(COLORS.get(self.model.state, "#8b8d98")))
            h = 8 + int(20 * self.model.bar()) if self.model.state in ("recording", "handsfree", "command") else 10
            p.drawRoundedRect(QRect(18, (self.height() - h) // 2, 10, h), 5, 5)
            p.setPen(QColor("#ededef"))
            p.setFont(QFont("Segoe UI" if sys.platform == "win32" else "Helvetica Neue", 11))
            p.drawText(QRect(40, 0, self.width() - 52, self.height()), Qt.AlignmentFlag.AlignVCenter, self.model.text())

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == "darwin" and app.platformName() == "cocoa":
        try:  # an accessory app: no Dock icon, and its panel can float over other apps' full-screen Spaces
            import AppKit

            AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        except Exception:
            pass
    _overlay = Overlay()  # keep a reference, or Qt garbage-collects the window
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    threading.Thread(target=background, daemon=True, name="controller").start()
    app.exec()


def _no_activate(widget) -> None:
    """Windows: WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, so clicking or showing it never steals focus. macOS: show on
    every Space and over full-screen apps."""
    if sys.platform == "darwin":
        _mac_all_spaces(widget)
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT = -20, 0x08000000, 0x00000080, 0x00000020
        user32 = ctypes.windll.user32
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT)
    except Exception:
        pass


unavailable_reason = ""


def available() -> bool:
    global unavailable_reason
    try:
        import PySide6
    except ImportError:
        unavailable_reason = "PySide6 isn't installed"
        return False
    if sys.platform == "darwin" and _plugins_hidden(PySide6.__file__):
        # Qt skips files with the macOS "hidden" flag and then aborts the whole process, so don't even try
        unavailable_reason = "Qt's plugins carry the macOS hidden flag: run `chflags -R nohidden .venv`"
        return False
    return True


def _plugins_hidden(pyside_init: str) -> bool:
    import os
    import stat

    folder = os.path.join(os.path.dirname(pyside_init), "Qt", "plugins", "platforms")
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".dylib")]
        return bool(names) and all(os.stat(os.path.join(folder, n)).st_flags & stat.UF_HIDDEN for n in names)
    except OSError:
        return False


def _mac_all_spaces(widget) -> None:
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "cocoa":
        return  # offscreen/minimal: winId() isn't an NSView
    try:
        import AppKit
        import objc

        window = objc.objc_object(c_void_p=int(widget.winId())).window()
        window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                                      | AppKit.NSWindowCollectionBehaviorStationary)
        window.setHidesOnDeactivate_(False)
    except Exception:
        pass

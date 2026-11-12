"""The context collector: what has keyboard focus.

- the app (process name) and window title: these pick the clean-up style;
- whether the focused field is a password field (we never paste into one, and never read it);
- the text just before the caret and the current selection: these feed the bias prompt's context terms (Phase 3),
  command mode (Phase 7), and learning from corrections (Phase 4).

Windows reads it through UI Automation (TextPattern, falling back to ValuePattern); macOS through the Accessibility
API (AXValue / AXSelectedTextRange). Everything stays in memory: context text is never stored.

Probes run on a daemon thread and the pipeline waits at most a short timeout (UI Automation can hang on a frozen
app)."""

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

BEFORE_CHARS = 600
FIELD_CHARS = 8000

last_error: str | None = None  # why the last password check couldn't tell, for the startup self-check


@dataclass
class FocusInfo:
    app: str | None = None
    is_password: bool | None = None  # None = couldn't tell
    title: str | None = None
    before_text: str = ""  # up to BEFORE_CHARS before the caret
    selected_text: str = ""
    field_text: str | None = None  # the whole field, only when asked for (learning)
    ms: int = 0


class FocusProbe:
    """Runs `probe` on a daemon thread; `result(timeout)` returns FocusInfo() if it didn't finish in time."""

    def __init__(self, probe: Callable[..., FocusInfo], full: bool = False):
        self._info: FocusInfo | None = None
        self._done = threading.Event()
        self._t0 = time.perf_counter()

        def run():
            try:
                self._info = probe(full=full) if full else probe()
            except Exception:
                self._info = FocusInfo()
            self._info.ms = int((time.perf_counter() - self._t0) * 1000)
            self._done.set()

        threading.Thread(target=run, daemon=True, name="focus-probe").start()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def result(self, timeout: float = 0.3) -> FocusInfo:
        return self._info if self._done.wait(timeout) and self._info else FocusInfo(ms=int((time.perf_counter() - self._t0) * 1000))


def platform_probe() -> Callable[..., FocusInfo]:
    if sys.platform == "win32":
        return _windows_probe
    if sys.platform == "darwin":
        return _mac_probe
    return lambda full=False: FocusInfo()


def warm() -> None:
    """Windows: generate the UI Automation COM wrappers now (takes ~1 s the first time) instead of on a dictation."""
    if sys.platform == "win32":
        try:
            import comtypes.client

            comtypes.client.GetModule("UIAutomationCore.dll")
        except Exception:
            pass


# --- Windows -----------------------------------------------------------------------------------------------------
UIA_TEXT_PATTERN, UIA_VALUE_PATTERN = 10014, 10002
ENDPOINT_START, ENDPOINT_END = 0, 1


def _windows_probe(full: bool = False) -> FocusInfo:
    app, title = _windows_app_and_title()
    info = FocusInfo(app=app, title=title)
    global last_error
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA

            uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
            el = uia.GetFocusedElement()
            if not el:
                return info
            info.is_password = bool(el.CurrentIsPassword)
            if info.is_password:
                return info  # never read a password field
            _windows_text(el, UIA, info, full)
        finally:
            comtypes.CoUninitialize()
    except Exception as exc:
        last_error = f"UI Automation: {type(exc).__name__}: {exc}"[:200]
    return info


def _windows_text(el, UIA, info: FocusInfo, full: bool) -> None:
    try:
        pat = el.GetCurrentPattern(UIA_TEXT_PATTERN)
        if pat:
            tp = pat.QueryInterface(UIA.IUIAutomationTextPattern)
            doc = tp.DocumentRange
            sel = tp.GetSelection()
            if sel and sel.Length:
                r = sel.GetElement(0)
                info.selected_text = (r.GetText(4000) or "").strip()
                before = doc.Clone()
                before.MoveEndpointByRange(ENDPOINT_END, r, ENDPOINT_START)
                info.before_text = (before.GetText(-1) or "")[-BEFORE_CHARS:]
            if full:
                info.field_text = (doc.GetText(FIELD_CHARS) or "")
            return
    except Exception:
        pass
    try:
        pat = el.GetCurrentPattern(UIA_VALUE_PATTERN)
        if pat:
            value = pat.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or ""
            info.before_text = value[-BEFORE_CHARS:]  # no caret position from ValuePattern: assume the end
            if full:
                info.field_text = value[:FIELD_CHARS]
    except Exception:
        pass


def _windows_app_and_title() -> tuple[str | None, str | None]:
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    hwnd = user32.GetForegroundWindow()
    tbuf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, tbuf, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    app = None
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                app = buf.value.rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(h)
    return app, tbuf.value or None


# --- macOS -------------------------------------------------------------------------------------------------------
def _mac_probe(full: bool = False) -> FocusInfo:
    info = FocusInfo()
    pid = None
    try:
        from AppKit import NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front:
            info.app, pid = str(front.localizedName()), int(front.processIdentifier())
    except Exception:
        pass
    info.is_password = _mac_secure_input()
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication, AXUIElementCreateSystemWide

        def attr(el, name):
            err, val = AXUIElementCopyAttributeValue(el, name, None)
            return None if err else val

        app_el = AXUIElementCreateApplication(pid) if pid else None
        if app_el is not None and pid not in _ax_enabled:
            _enable_electron_ax(app_el, pid)
        win = attr(app_el, "AXFocusedWindow") if app_el is not None else None
        if win is not None:
            t = attr(win, "AXTitle")
            info.title = str(t) if t else None
        # Ask the app first: Electron apps answer there once AXManualAccessibility is on, not system-wide
        el = (attr(app_el, "AXFocusedUIElement") if app_el is not None else None) or attr(AXUIElementCreateSystemWide(), "AXFocusedUIElement")
        if el is None:
            global last_error
            last_error = "Accessibility permission isn't granted" if not _mac_trusted() else f"{info.app or 'the front app'} doesn't expose its text field"
            return info
        if str(attr(el, "AXSubrole") or "") == "AXSecureTextField":
            info.is_password = True
        if info.is_password:
            return info
        if info.is_password is None:
            info.is_password = False
        value = attr(el, "AXValue")
        value = str(value) if isinstance(value, str) or hasattr(value, "UTF8String") else ""
        sel = attr(el, "AXSelectedText")
        info.selected_text = str(sel).strip() if sel else ""
        caret = len(value)
        rng = attr(el, "AXSelectedTextRange")
        if rng is not None:
            try:
                from ApplicationServices import AXValueGetValue, kAXValueCFRangeType

                ok, r = AXValueGetValue(rng, kAXValueCFRangeType, None)
                if ok:
                    caret = int(r.location)
            except Exception:
                pass
        info.before_text = value[:caret][-BEFORE_CHARS:]
        if full:
            info.field_text = value[:FIELD_CHARS]
    except Exception as exc:
        last_error = f"Accessibility: {type(exc).__name__}"
    return info


_ax_enabled: set[int] = set()


def _enable_electron_ax(app_el, pid: int) -> None:
    """Electron apps (Slack, VS Code, Discord, Notion...) build their accessibility tree only when a client asks."""
    try:
        from ApplicationServices import AXUIElementSetAttributeValue

        AXUIElementSetAttributeValue(app_el, "AXManualAccessibility", True)
    except Exception:
        pass
    _ax_enabled.add(pid)


def _mac_trusted() -> bool:
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def detection_problem() -> str | None:
    """Why password fields can't be detected on this machine, or None when they can. Checked once at startup, so it
    looks at the permission (macOS) rather than at whichever app happens to be in front."""
    if sys.platform == "darwin":
        return None if _mac_trusted() else "Accessibility permission isn't granted"
    info = platform_probe()()
    return None if info.is_password is not None else (last_error or "unsupported OS")


def _mac_secure_input() -> bool | None:
    # Secure Event Input is on whenever a password field has focus (and when Terminal's Secure Keyboard Entry is on).
    try:
        import ctypes

        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        return True if carbon.IsSecureEventInputEnabled() else None
    except Exception:
        return None

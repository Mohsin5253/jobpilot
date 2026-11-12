"""What has keyboard focus: the app, and whether it's a password field (we never paste into one).

Phase 1 reads only these two facts. Phase 2 adds the window title and nearby text for the bias prompt.

The check starts on a background thread the moment the key comes up, so it runs while the audio is being
transcribed, and the pipeline waits at most a short timeout for it (UI Automation can hang on a frozen app)."""

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable


last_error: str | None = None  # why the last password check couldn't tell, for the startup self-check


@dataclass
class FocusInfo:
    app: str | None = None
    is_password: bool | None = None  # None = couldn't tell
    ms: int = 0


class FocusProbe:
    """Runs `probe` on a daemon thread; `result(timeout)` returns FocusInfo() if it didn't finish in time."""

    def __init__(self, probe: Callable[[], FocusInfo]):
        self._info: FocusInfo | None = None
        self._done = threading.Event()
        self._t0 = time.perf_counter()

        def run():
            try:
                self._info = probe()
            except Exception:
                self._info = FocusInfo()
            self._info.ms = int((time.perf_counter() - self._t0) * 1000)
            self._done.set()

        threading.Thread(target=run, daemon=True, name="focus-probe").start()

    def result(self, timeout: float = 0.3) -> FocusInfo:
        return self._info if self._done.wait(timeout) and self._info else FocusInfo(ms=int((time.perf_counter() - self._t0) * 1000))


def platform_probe() -> Callable[[], FocusInfo]:
    if sys.platform == "win32":
        return _windows_probe
    if sys.platform == "darwin":
        return _mac_probe
    return lambda: FocusInfo()


def warm() -> None:
    """Windows: generate the UI Automation COM wrappers now (takes ~1 s the first time) instead of on a dictation."""
    if sys.platform == "win32":
        try:
            import comtypes.client

            comtypes.client.GetModule("UIAutomationCore.dll")
        except Exception:
            pass


# --- Windows -----------------------------------------------------------------------------------------------------
def _windows_probe() -> FocusInfo:
    return FocusInfo(app=_windows_app(), is_password=_windows_is_password())


def _windows_app() -> str | None:
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    hwnd = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1]
        return None
    finally:
        kernel32.CloseHandle(h)


def _windows_is_password() -> bool | None:
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation

            uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
            el = uia.GetFocusedElement()
            return bool(el.CurrentIsPassword) if el else None
        finally:
            comtypes.CoUninitialize()
    except Exception as exc:
        global last_error
        last_error = f"UI Automation: {type(exc).__name__}: {exc}"[:200]
        return None


# --- macOS -------------------------------------------------------------------------------------------------------
def _mac_probe() -> FocusInfo:
    app = None
    try:
        from AppKit import NSWorkspace

        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        app = str(front.localizedName()) if front else None
    except Exception:
        pass
    return FocusInfo(app=app, is_password=_mac_is_password())


def _mac_is_password() -> bool | None:
    # Secure Event Input is on whenever a password field has focus (and when Terminal's Secure Keyboard Entry is on).
    try:
        import ctypes

        carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
        if carbon.IsSecureEventInputEnabled():
            return True
    except Exception:
        pass
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateSystemWide

        err, el = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), "AXFocusedUIElement", None)
        if err or el is None:
            global last_error
            last_error = f"Accessibility error {err} (is Accessibility permission granted?)"
            return None
        err, sub = AXUIElementCopyAttributeValue(el, "AXSubrole", None)
        return (str(sub) == "AXSecureTextField") if not err else False
    except Exception:
        return None

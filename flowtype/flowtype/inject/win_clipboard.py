"""Windows clipboard through the Win32 API (ctypes, no pywin32). Every memory-backed format is saved byte for byte
(text, Unicode text, HTML, RTF, images as DIB, copied files as CF_HDROP, app-specific formats); GDI-handle formats
(CF_BITMAP, metafiles) are skipped because Windows re-creates them from the DIB."""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.GetClipboardSequenceNumber.argtypes = []
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13
HWND_MESSAGE = wintypes.HWND(-3)
# Handle-based formats that can't be copied as bytes (and are synthesised from others anyway).
SKIP = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E} | set(range(0x0200, 0x0400))
MAX_FORMAT_BYTES = 32 * 1024 * 1024


class WinClipboard:
    def __init__(self):
        self._hwnd = None
        self._no_history = [user32.RegisterClipboardFormatW(n) for n in
                            ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")]

    def _owner(self):
        # SetClipboardData fails after EmptyClipboard if the clipboard was opened without an owner window.
        if self._hwnd is None:
            self._hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
        return self._hwnd

    def _open(self) -> None:
        hwnd = self._owner()
        for _ in range(20):  # another app may hold it for a moment
            if user32.OpenClipboard(hwnd):
                return
            time.sleep(0.01)
        raise OSError("the clipboard is busy (another app has it open)")

    def snapshot(self) -> list[tuple[int, bytes]]:
        self._open()
        try:
            out: list[tuple[int, bytes]] = []
            fmt = user32.EnumClipboardFormats(0)
            while fmt:
                if fmt not in SKIP:
                    data = self._read(fmt)
                    if data is not None:
                        out.append((fmt, data))
                fmt = user32.EnumClipboardFormats(fmt)
            return out
        finally:
            user32.CloseClipboard()

    def set_text(self, text: str) -> None:
        self._write([(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))], hide_from_history=True)

    def restore(self, snap: list[tuple[int, bytes]]) -> None:
        # The original is already in clipboard history; don't add it a second time.
        self._write(snap, hide_from_history=True)

    def get_text(self) -> str | None:
        self._open()
        try:
            data = self._read(CF_UNICODETEXT)
        finally:
            user32.CloseClipboard()
        return data.decode("utf-16-le", errors="ignore").split("\0", 1)[0] if data else None

    def change_marker(self) -> int:
        return int(user32.GetClipboardSequenceNumber())

    @staticmethod
    def _read(fmt: int) -> bytes | None:
        h = user32.GetClipboardData(fmt)
        if not h:
            return None
        size = kernel32.GlobalSize(h)
        if not size or size > MAX_FORMAT_BYTES:
            return None
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return None
        try:
            return ctypes.string_at(ptr, size)
        finally:
            kernel32.GlobalUnlock(h)

    def _write(self, items: list[tuple[int, bytes]], hide_from_history: bool) -> None:
        if hide_from_history:
            have = {f for f, _ in items}
            items = [*items, *((f, b"\0\0\0\0") for f in self._no_history if f and f not in have)]
        self._open()
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for fmt, data in items:
                h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
                if not h:
                    raise MemoryError("GlobalAlloc failed")
                ptr = kernel32.GlobalLock(h)
                ctypes.memmove(ptr, data, len(data))
                kernel32.GlobalUnlock(h)
                if not user32.SetClipboardData(fmt, h):  # on success the system owns the memory
                    kernel32.GlobalFree(h)
        finally:
            user32.CloseClipboard()

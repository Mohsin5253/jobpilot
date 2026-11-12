"""Start Flowtype when you log in.

- Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (per user, no admin rights).
- macOS: a LaunchAgent plist in ~/Library/LaunchAgents.
- Linux: an XDG autostart .desktop file.

The command is the packaged executable when frozen (PyInstaller), else `pythonw -m flowtype` from this venv."""

import plistlib
import shlex
import sys
from pathlib import Path

APP_ID = "com.flowtype.dictation"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"  # no console window
    return [str(exe), "-m", "flowtype", "run"]


def _win_cmdline(cmd: list[str]) -> str:
    return " ".join(f'"{c}"' if " " in c else c for c in cmd)


def mac_plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def linux_desktop_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "autostart" / "flowtype.desktop"


def enable(platform: str = sys.platform, home: Path | None = None, registry=None, cmd: list[str] | None = None) -> str:
    cmd = cmd or command()
    if platform == "win32":
        reg = registry if registry is not None else _WinRegistry()
        reg.set(RUN_KEY, "Flowtype", _win_cmdline(cmd))
        return f"HKCU\\{RUN_KEY}\\Flowtype"
    if platform == "darwin":
        path = mac_plist_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        from flowtype.config import data_dir

        log = str(data_dir() / "flowtype.log")
        path.write_bytes(plistlib.dumps({"Label": APP_ID, "ProgramArguments": cmd, "RunAtLoad": True, "KeepAlive": False,
                                         "ProcessType": "Interactive", "StandardOutPath": log, "StandardErrorPath": log}))
        return str(path)
    path = linux_desktop_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[Desktop Entry]\nType=Application\nName=Flowtype\nExec={shlex.join(cmd)}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
    return str(path)


def disable(platform: str = sys.platform, home: Path | None = None, registry=None) -> bool:
    if platform == "win32":
        return (registry if registry is not None else _WinRegistry()).delete(RUN_KEY, "Flowtype")
    path = mac_plist_path(home) if platform == "darwin" else linux_desktop_path(home)
    if path.exists():
        path.unlink()
        return True
    return False


def status(platform: str = sys.platform, home: Path | None = None, registry=None) -> str | None:
    if platform == "win32":
        return (registry if registry is not None else _WinRegistry()).get(RUN_KEY, "Flowtype")
    path = mac_plist_path(home) if platform == "darwin" else linux_desktop_path(home)
    return str(path) if path.exists() else None


class _WinRegistry:
    def set(self, key: str, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def get(self, key: str, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                return winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            return None

    def delete(self, key: str, name: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
            return True
        except FileNotFoundError:
            return False

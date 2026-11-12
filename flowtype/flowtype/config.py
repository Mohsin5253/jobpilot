"""Settings. Defaults live here; a user's `config.toml` (in the data folder) overrides any of them. Secrets are never
in this file: API keys live in the OS keychain (see secrets.py)."""

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


def data_dir() -> Path:
    """Where everything Flowtype keeps lives: config.toml and flowtype.db. Nothing is stored anywhere else."""
    if override := os.environ.get("FLOWTYPE_HOME"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Flowtype"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Flowtype"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "flowtype"


@dataclass
class HotkeyConfig:
    key: str = "ctrl_r"  # a pynput Key name: ctrl_r, alt_r, cmd_r, f13...
    tap_max_ms: int = 250  # a press shorter than this is a tap, not a hold
    double_tap_gap_ms: int = 350  # two taps within this gap toggle hands-free
    max_record_s: int = 120  # a recording stops itself after this long


@dataclass
class AudioConfig:
    device: str = ""  # input device name or index; "" = system default
    preroll_ms: int = 400  # audio kept from before the key went down (300-500 ms)
    postroll_ms: int = 250  # audio kept after the key comes up
    target_dbfs: float = -3.0  # peak-normalise to this level
    max_gain_db: float = 30.0  # never amplify more than this (keeps quiet noise quiet)


@dataclass
class VADConfig:
    threshold: float = 0.5
    min_speech_ms: int = 250  # less speech than this in total = nothing is pasted
    pad_ms: int = 200  # kept around the first and last speech


@dataclass
class ASRConfig:
    provider: str = "groq"
    model: str = "whisper-large-v3-turbo"
    language: str = "en"  # pinned; Hinglish is also "en" so Whisper writes it in Roman script
    style: str = "en-IN"  # "en-IN" or "hinglish": picks the style sample at the start of the bias prompt
    timeout_s: float = 10.0
    base_url: str = "https://api.groq.com/openai/v1"


@dataclass
class LLMConfig:
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    enabled: bool = False  # the clean-up pass is Phase 2
    timeout_s: float = 6.0
    base_url: str = "https://api.groq.com/openai/v1"


@dataclass
class InjectConfig:
    restore_delay_ms: int = 150  # the clipboard is put back this long after the paste
    refuse_password_fields: bool = True


@dataclass
class StoreConfig:
    store_text: bool = False  # off by default: only timings and counts are kept unless you opt in


@dataclass
class DictionaryConfig:
    words: list[str] = field(default_factory=list)  # extra words; `flowtype words add` keeps them in the database


@dataclass
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    inject: InjectConfig = field(default_factory=InjectConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    dictionary: DictionaryConfig = field(default_factory=DictionaryConfig)


def _apply(obj, values: dict, where: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for k, v in values.items():
        if k not in known:
            raise ValueError(f"Unknown setting {where}.{k} in config.toml")
        cur = getattr(obj, k)
        if is_dataclass(cur):
            if not isinstance(v, dict):
                raise ValueError(f"[{where}.{k}] must be a table")
            _apply(cur, v, f"{where}.{k}" if where else k)
        else:
            setattr(obj, k, v)


def load(path: Path | None = None) -> Config:
    cfg = Config()
    path = path or data_dir() / "config.toml"
    if path.exists():
        with path.open("rb") as f:
            _apply(cfg, tomllib.load(f), "")
    return cfg

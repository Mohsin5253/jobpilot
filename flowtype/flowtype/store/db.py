"""Local SQLite: one row per dictation with per-stage latencies, and the personal dictionary. Nothing leaves the
machine. Transcript text is stored only when `store.store_text` is on; audio is never stored."""

import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,              -- hold | handsfree | file
    status TEXT NOT NULL,            -- pasted | no_speech | empty | refused_password | error
    error TEXT,
    app TEXT,                        -- the focused app (process name), when known
    asr_model TEXT,
    language TEXT,
    asr_retried INTEGER NOT NULL DEFAULT 0,
    guard_dropped TEXT,              -- comma-separated reasons
    audio_ms INTEGER,                -- captured audio, pre-roll and post-roll included
    speech_ms INTEGER,               -- speech the VAD found
    postroll_ms INTEGER,             -- waiting for the post-roll after the key came up
    vad_ms INTEGER,
    normalise_ms INTEGER,
    prompt_ms INTEGER,
    asr_ms INTEGER,                  -- first ASR call, network included
    asr_retry_ms INTEGER,
    guard_ms INTEGER,
    dictionary_ms INTEGER,
    context_ms INTEGER,              -- focused-field check
    inject_ms INTEGER,               -- clipboard set + paste keystroke
    total_ms INTEGER,                -- key up -> text pasted
    chars INTEGER,
    words INTEGER,
    text TEXT                        -- only with store_text = true
);
CREATE TABLE IF NOT EXISTS dictionary (
    term TEXT PRIMARY KEY COLLATE NOCASE,
    starred INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',   -- manual | learned (Phase 2)
    uses INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL
);
"""

STAGES = ["postroll_ms", "vad_ms", "normalise_ms", "prompt_ms", "asr_ms", "asr_retry_ms", "guard_ms", "dictionary_ms", "context_ms", "inject_ms", "total_ms"]


@dataclass
class Dictation:
    mode: str
    status: str = "pending"
    error: str | None = None
    app: str | None = None
    asr_model: str | None = None
    language: str | None = None
    asr_retried: bool = False
    guard_dropped: str | None = None
    audio_ms: int | None = None
    speech_ms: int | None = None
    postroll_ms: int | None = None
    vad_ms: int | None = None
    normalise_ms: int | None = None
    prompt_ms: int | None = None
    asr_ms: int | None = None
    asr_retry_ms: int | None = None
    guard_ms: int | None = None
    dictionary_ms: int | None = None
    context_ms: int | None = None
    inject_ms: int | None = None
    total_ms: int | None = None
    chars: int | None = None
    words: int | None = None
    text: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # --- dictations ---------------------------------------------------------------------------------------------
    def add_dictation(self, d: Dictation, store_text: bool = False) -> int:
        row = asdict(d)
        row["asr_retried"] = int(d.asr_retried)
        if not store_text:
            row["text"] = None
        cols = ", ".join(row)
        with self._lock, self._db:
            cur = self._db.execute(f"INSERT INTO dictations ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute("SELECT * FROM dictations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def latency_summary(self, last: int = 200) -> dict[str, dict[str, float]]:
        """p50 / p95 per stage over the last `last` pasted dictations."""
        with self._lock:
            rows = self._db.execute(f"SELECT {', '.join(STAGES)} FROM dictations WHERE status = 'pasted' ORDER BY id DESC LIMIT ?", (last,)).fetchall()
        out = {}
        for stage in STAGES:
            vals = sorted(r[stage] for r in rows if r[stage] is not None)
            if vals:
                out[stage] = {"p50": _pct(vals, 50), "p95": _pct(vals, 95), "n": len(vals)}
        return out

    # --- dictionary ---------------------------------------------------------------------------------------------
    def add_word(self, term: str, starred: bool = False, source: str = "manual") -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO dictionary (term, starred, source, added_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(term) DO UPDATE SET starred = MAX(starred, excluded.starred)",
                (term.strip(), int(starred), source, now),
            )

    def remove_word(self, term: str) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM dictionary WHERE term = ?", (term.strip(),)).rowcount > 0

    def words(self) -> list[sqlite3.Row]:
        """Most relevant first: most used, then newest."""
        with self._lock:
            return self._db.execute("SELECT term, starred, source, uses FROM dictionary ORDER BY uses DESC, added_at DESC").fetchall()

    def bump_uses(self, terms: list[str]) -> None:
        if terms:
            with self._lock, self._db:
                self._db.executemany("UPDATE dictionary SET uses = uses + 1 WHERE term = ?", [(t,) for t in terms])

    def close(self) -> None:
        self._db.close()


def _pct(sorted_vals: list[float], p: int) -> float:
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo), 1)

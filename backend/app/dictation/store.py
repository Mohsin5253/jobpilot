"""Dictation metrics: per-stage latency and the Dictation Edit Rate (share of dictations edited before submitting).
By design no audio and no transcript text is stored: timings, word counts and edit ratios only."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Dictation


def _pct(xs: list[float], p: float) -> int | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return int(xs[k])


async def metrics(session, user_id: uuid.UUID | None = None, days: int = 30) -> dict:
    q = select(Dictation).where(Dictation.created_at >= datetime.now(UTC) - timedelta(days=days))
    if user_id is not None:
        q = q.where(Dictation.user_id == user_id)
    rows = (await session.execute(q)).scalars().all()
    judged = [r for r in rows if r.edited is not None]
    polished = [r for r in rows if r.mode == "polished" and r.guard not in ("", "skipped")]

    def edit_rate(rs):
        rs = [r for r in rs if r.edited is not None]
        return round(sum(1 for r in rs if r.edited) / len(rs), 3) if rs else None

    return {
        "dictations": len(rows),
        "edit_rate": round(sum(1 for r in judged if r.edited) / len(judged), 3) if judged else None,
        "avg_edit_ratio": round(sum(r.edit_ratio or 0 for r in judged) / len(judged), 3) if judged else None,
        "latency_ms": {
            stage: {"p50": _pct([getattr(r, stage) for r in rows], 50), "p95": _pct([getattr(r, stage) for r in rows], 95)}
            for stage in ("asr_ms", "server_ms", "client_ms")
        },
        "fallback_rate": round(sum(1 for r in rows if r.fallback) / len(rows), 3) if rows else None,
        # Polished mode: how often the clean-up was thrown away (guardrail) or ran out of time, and Edit Rate per mode.
        "cleanup": {
            "runs": len(polished),
            "accepted_rate": round(sum(1 for r in polished if r.guard == "ok") / len(polished), 3) if polished else None,
            "guard_rejection_rate": round(sum(1 for r in polished if r.guard.startswith("rejected")) / len(polished), 3) if polished else None,
            "timeout_rate": round(sum(1 for r in polished if r.guard in ("timeout", "error")) / len(polished), 3) if polished else None,
            "llm_ms": {"p50": _pct([r.llm_ms for r in polished], 50), "p95": _pct([r.llm_ms for r in polished], 95)},
        },
        "edit_rate_by_mode": {m: edit_rate([r for r in rows if r.mode == m]) for m in ("polished", "verbatim")},
    }

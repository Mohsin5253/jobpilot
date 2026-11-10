"""The feedback loop nobody else closes: what happened to each application, and what that teaches.

Headline metric: interviews per application. Then the funnel, conversion by resume version (A experience
first / B projects first), by fit-score band, by source and by track, and the likely rejection reasons:
the skills most often missing across applications that were rejected or went silent.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobMatch

POSITIVE = {"replied", "interview", "offer"}
INTERVIEWED = {"interview", "offer"}
MIN_SAMPLE = 10  # below this, a comparison is "too few to tell"


def _rate(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def _group(rows: list[tuple[JobMatch, Job]], key) -> list[dict]:
    groups: dict[str, list[JobMatch]] = {}
    for m, j in rows:
        groups.setdefault(key(m, j), []).append(m)
    out = []
    for name, ms in sorted(groups.items()):
        interviews = sum(m.outcome in INTERVIEWED for m in ms)
        replies = sum(m.outcome in POSITIVE for m in ms)
        out.append(
            {
                "key": name,
                "applied": len(ms),
                "replies": replies,
                "interviews": interviews,
                "interview_rate": _rate(interviews, len(ms)),
                "reply_rate": _rate(replies, len(ms)),
                "enough_data": len(ms) >= MIN_SAMPLE,
            }
        )
    return out


def _band(score: float) -> str:
    return "80+" if score >= 80 else "70–79" if score >= 70 else "60–69" if score >= 60 else "under 60"


def rejection_gaps(rows: list[JobMatch], limit: int = 6) -> list[dict]:
    """Skills most often missing where it didn't work out: the likely reasons, and what to fix first."""
    missed = [m for m in rows if m.outcome in ("rejected", "no_reply")]
    counts = Counter(g for m in missed for g in m.gaps or [])
    return [{"skill": s, "count": c, "share": _rate(c, len(missed))} for s, c in counts.most_common(limit)]


async def insights(s: AsyncSession, user_ids: list[uuid.UUID]) -> dict:
    rows = (
        await s.execute(select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id).where(JobMatch.user_id.in_(user_ids), JobMatch.applied_at.is_not(None)))
    ).unique().all()
    applied = [m for m, _ in rows]
    n = len(applied)
    counts = Counter(m.outcome for m in applied)
    interviews = counts["interview"] + counts["offer"]
    replies = interviews + counts["replied"]
    now = datetime.now(UTC)
    waiting = [m for m in applied if m.outcome == "none" and m.applied_at and now - m.applied_at > timedelta(days=7)]
    reasons = Counter(m.rejection_reason for m in applied if m.outcome == "rejected" and m.rejection_reason)
    return {
        "applied": n,
        "interview_rate": _rate(interviews, n),
        "reply_rate": _rate(replies, n),
        "funnel": {
            "applied": n,
            "replied": replies,
            "interview": interviews,
            "offer": counts["offer"],
            "rejected": counts["rejected"],
            "no_reply": counts["no_reply"],
            "awaiting": counts["none"],
        },
        "by_variant": _group(rows, lambda m, j: {"A": "A · experience first", "B": "B · projects first"}.get(m.resume_variant, m.resume_variant)),
        "by_band": _group(rows, lambda m, j: _band(m.score)),
        "by_source": _group(rows, lambda m, j: j.publisher or j.source),
        "by_track": _group(rows, lambda m, j: "Technical" if j.track == "technical" else "Non-technical"),
        "rejection_gaps": rejection_gaps(applied),
        "reasons": [{"reason": r, "count": c} for r, c in reasons.most_common(6)],
        "needs_outcome": [
            {"match_id": str(m.id), "company": j.company, "title": j.title, "applied_at": m.applied_at.isoformat()}
            for m, j in rows
            if m in waiting
        ][:10],
        "min_sample": MIN_SAMPLE,
    }

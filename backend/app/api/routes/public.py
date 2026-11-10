"""Public, sign-in-free numbers for the landing page: live beta counters computed from real tables.

Everything here is an aggregate over all accounts (never a single user's data) and excludes throwaway demo
accounts. Answers are cached in-process for five minutes and marked cacheable for the same time, so a busy
landing page costs one set of COUNT queries per five minutes.
"""

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.config import settings
from app.models import AgentRun, DraftStatus, Job, OutreachDraft, RunStatus, User

router = APIRouter(tags=["public"])

CACHE_S = 300
COST_WINDOW = timedelta(days=30)


class PublicStats(BaseModel):
    beta: bool = True
    postings_verified: int  # postings the Verifier has checked
    scams_flagged: int  # of those, blocked as suspicious (never matched to anyone)
    applications_approved: int  # drafts a student approved (approved or sent), demo accounts excluded
    runs_counted: int  # finished runs in the cost window, demo accounts excluded
    avg_cost_inr_per_run: float | None  # mean AI cost of those runs in rupees; None until there is a run
    usd_inr_rate: float  # the conversion used: AI providers bill in USD
    cost_window_days: int
    as_of: datetime


_cache: tuple[float, PublicStats] | None = None


async def _compute(session) -> PublicStats:
    now = datetime.now(UTC)
    verified, flagged = (
        await session.execute(
            select(func.count().filter(Job.legit_checked_at.is_not(None)), func.count().filter(Job.legit_status == "suspicious"))
        )
    ).one()
    approved = (
        await session.execute(
            select(func.count())
            .select_from(OutreachDraft)
            .join(User, User.id == OutreachDraft.user_id)
            .where(OutreachDraft.status.in_([DraftStatus.approved, DraftStatus.sent]), User.is_demo.is_(False))
        )
    ).scalar_one()
    runs, avg_usd = (
        await session.execute(
            select(func.count(), func.avg(AgentRun.cost_usd))
            .join(User, User.id == AgentRun.user_id)
            .where(
                AgentRun.created_at >= now - COST_WINDOW,
                AgentRun.status.in_([RunStatus.completed, RunStatus.awaiting_approval]),
                User.is_demo.is_(False),
            )
        )
    ).one()
    rate = settings.usd_inr_rate
    return PublicStats(
        postings_verified=verified,
        scams_flagged=flagged,
        applications_approved=approved,
        runs_counted=runs,
        avg_cost_inr_per_run=round(float(avg_usd) * rate, 2) if runs and avg_usd is not None else None,
        usd_inr_rate=rate,
        cost_window_days=COST_WINDOW.days,
        as_of=now,
    )


@router.get("/public/stats", response_model=PublicStats)
async def public_stats(session: SessionDep, response: Response) -> PublicStats:
    global _cache
    if _cache is None or _cache[0] <= time.monotonic():
        _cache = (time.monotonic() + CACHE_S, await _compute(session))
    response.headers["cache-control"] = f"public, max-age={CACHE_S}, s-maxage={CACHE_S}"
    return _cache[1]


def reset_cache() -> None:
    global _cache
    _cache = None

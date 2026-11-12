"""Quality quota (F5): a daily cap on approved sends, a send-worthiness score shown before each approval, an audit
event for every approve / reject / send, and the weekly "we skipped N weak or risky matches for you" report.

The cap defaults to 5 a day and the student can raise it to their plan's maximum (Free 10). It's enforced here,
server-side, with one atomic upsert per approval, and resets at midnight IST.
"""

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import AgentRun, ApprovalEvent, Consent, Job, JobMatch, OutreachDraft, Profile, Quota, TailoredResume, User
from app.schemas import Preferences
from app.safety import egress

IST = ZoneInfo("Asia/Kolkata")


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(IST).date()


def plan_max(user: User) -> int:
    return int(settings.limits(user.plan)["sends_per_day_max"])


def effective_cap(user: User) -> int:
    return max(1, min(user.daily_send_cap or 5, plan_max(user)))


class QuotaExceeded(HTTPException):
    def __init__(self, cap: int, mx: int):
        more = f" You can raise it to {mx} in Settings." if cap < mx else ""
        super().__init__(429, f"You’ve used today’s {cap} approved sends. The quota resets at midnight IST.{more}")


async def state(s: AsyncSession, user: User) -> dict:
    day = today_ist()
    used = (await s.execute(select(Quota.sends_used).where(Quota.user_id == user.id, Quota.date == day))).scalar_one_or_none() or 0
    cap = effective_cap(user)
    midnight = datetime.combine(day + timedelta(days=1), datetime.min.time(), IST)
    return {"cap": cap, "used": used, "remaining": max(0, cap - used), "max": plan_max(user), "resets_at": midnight.isoformat()}


async def consume(s: AsyncSession, user: User) -> int:
    """Counts one approved send against today's cap; raises QuotaExceeded when it's used up. Atomic across workers."""
    cap = effective_cap(user)
    row = (
        await s.execute(
            text(
                "INSERT INTO quotas (user_id, date, sends_used, cap) VALUES (:u, :d, 1, :cap) "
                "ON CONFLICT (user_id, date) DO UPDATE SET sends_used = quotas.sends_used + 1, cap = :cap "
                "WHERE quotas.sends_used < :cap RETURNING sends_used"
            ),
            {"u": user.id, "d": today_ist(), "cap": cap},
        )
    ).scalar_one_or_none()
    if row is None:
        raise QuotaExceeded(cap, plan_max(user))
    return row


async def refund(s: AsyncSession, user_id) -> None:
    """An approval was undone before sending (the draft was edited, or its approval no longer matched): give the
    day's send back."""
    await s.execute(text("UPDATE quotas SET sends_used = sends_used - 1 WHERE user_id = :u AND date = :d AND sends_used > 0"), {"u": user_id, "d": today_ist()})


async def set_cap(s: AsyncSession, user: User, cap: int) -> None:
    mx = plan_max(user)
    if not 1 <= cap <= mx:
        raise HTTPException(422, f"Choose between 1 and {mx} a day on your plan")
    user.daily_send_cap = cap
    await s.execute(text("UPDATE quotas SET cap = :cap WHERE user_id = :u AND date = :d"), {"cap": cap, "u": user.id, "d": today_ist()})


def ip_hash(request: Request | None) -> str:
    if request is None:
        return ""
    from app.services.ratelimit import client_ip

    return hashlib.sha256(f"{settings.jwt_secret}:{client_ip(request)}".encode()).hexdigest()


async def record(s: AsyncSession, draft_id: uuid.UUID, user_id: uuid.UUID, action: str, channel: str = "web", request: Request | None = None) -> None:
    s.add(ApprovalEvent(application_id=draft_id, user_id=user_id, action=action, channel=channel, ip_hash=ip_hash(request)))


def send_worthiness(match: JobMatch, job: Job, draft: OutreachDraft, tailored: TailoredResume | None, proof_published: bool) -> tuple[int, dict[str, int]]:
    """0-100: how good an application this is likely to be. Fit 40, verification 25, not-a-ghost 15, completeness 20."""
    fit = round(max(0.0, min(100.0, match.score or 0)) * 0.40)
    verified = {"verified": 25, "caution": 10, "suspicious": 0}.get(job.legit_status or "", 12)
    ghost = round((100 - (job.ghost_score if job.ghost_score is not None else 30)) * 0.15)
    complete = 0
    complete += 6 if (draft.to_email or job.recruiter_email) else 0
    complete += 6 if tailored and tailored.bullets else 0
    complete += 4 if tailored and (tailored.guard_report or {}).get("passed", True) else 0
    complete += 4 if proof_published else 0
    parts = {"fit": fit, "verification": verified, "not_ghost": ghost, "completeness": complete}
    return min(100, sum(parts.values())), parts


async def weekly_report(now: datetime | None = None) -> int:
    """Mondays: tells each active student what the crew skipped for them in the last 7 days (email, and WhatsApp
    when they've opted in to the digest). Returns the number of reports sent."""
    from app.services.mailer import send_system_email

    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    sent = 0
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724007)"))).scalar():
            return 0
        users = (await s.execute(select(User).where(User.is_demo.is_(False), func.coalesce(User.last_seen_at, User.created_at) >= now - timedelta(days=30)))).scalars().all()
        for u in users:
            prof = (await s.execute(select(Profile).where(Profile.user_id == u.id))).scalar_one_or_none()
            min_score = Preferences.model_validate((prof.preferences if prof else {}) or {}).min_score
            blocked = (
                await s.execute(select(func.coalesce(func.sum(AgentRun.stats["suspicious"].as_integer()), 0)).where(AgentRun.user_id == u.id, AgentRun.created_at >= since))
            ).scalar_one()
            weak, ghosts, strong = (
                await s.execute(
                    select(
                        func.count().filter(JobMatch.score < min_score),
                        func.count().filter(JobMatch.score >= min_score, Job.ghost_risk == "high"),
                        func.count().filter(JobMatch.score >= min_score, Job.ghost_risk != "high"),
                    )
                    .join(Job, Job.id == JobMatch.job_id)
                    .where(JobMatch.user_id == u.id, JobMatch.created_at >= since)
                )
            ).one()
            skipped = int(blocked) + weak + ghosts
            if skipped == 0 and strong == 0:
                continue
            summary = (
                f"This week we skipped {skipped} weak or risky matches for you ({int(blocked)} likely scams, {weak} weak fits, "
                f"{ghosts} likely ghost jobs) and kept {strong} strong ones for your review."
            )
            if await send_system_email(u.email, "Your week: what JobPilot skipped for you", f"Hi {u.name or 'there'},\n\n{summary}\n\n{settings.app_url}/approvals"):
                sent += 1
            if settings.whatsapp_enabled and prof and prof.whatsapp_number:
                wa = (await s.execute(select(Consent.id).where(Consent.user_id == u.id, Consent.purpose == "whatsapp", Consent.withdrawn_at.is_(None)))).first()
                if wa:
                    import httpx

                    from app.services.whatsapp import send_template

                    try:
                        async with egress.client("whatsapp", timeout=15) as c:
                            await send_template(c, prof.whatsapp_number, [u.name or "there", summary])
                    except httpx.HTTPError as exc:
                        log.warning("weekly_report.whatsapp_failed", error=str(exc)[:200])
    log.info("weekly_report.sent", count=sent)
    return sent


async def draft_worthiness(s: AsyncSession, d: OutreachDraft, m: JobMatch, j: Job) -> tuple[int, dict[str, int]]:
    tailored = (await s.execute(select(TailoredResume).where(TailoredResume.match_id == m.id))).scalar_one_or_none()
    proof = (await s.execute(select(Consent.id).where(Consent.user_id == d.user_id, Consent.purpose == "public_proof", Consent.withdrawn_at.is_(None)))).first()
    return send_worthiness(m, j, d, tailored, proof is not None)

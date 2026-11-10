"""Plan limits (Free / Pro), measured over the last 24 hours. No payments yet: an admin switches plans."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope
from app.models import AgentRun, LLMCall, OutreachDraft, Profile, User

# Runs a person asks for (background refresh / daily / research runs don't count against the plan).
MANUAL = or_(AgentRun.trigger.in_(["manual", "prepare"]), and_(AgentRun.trigger == "research", AgentRun.params["force_research"].as_boolean().is_(True)))


async def usage_today(s: AsyncSession, user: User) -> dict:
    since = datetime.now(UTC) - timedelta(hours=24)
    limits = settings.limits(user.plan)
    drafts = (
        await s.execute(select(func.count()).where(OutreachDraft.user_id == user.id, OutreachDraft.kind == "application", OutreachDraft.created_at >= since))
    ).scalar_one()
    week = (
        await s.execute(
            select(func.count()).where(
                OutreachDraft.user_id == user.id, OutreachDraft.kind == "application", OutreachDraft.created_at >= datetime.now(UTC) - timedelta(days=7)
            )
        )
    ).scalar_one()
    profile = (await s.execute(select(Profile.preferences).where(Profile.user_id == user.id))).scalar_one_or_none() or {}
    weekly_cap = int(profile.get("weekly_application_cap") or settings.default_weekly_application_cap)
    runs = (
        await s.execute(
            select(func.count()).where(AgentRun.user_id == user.id, MANUAL, AgentRun.created_at >= since)
        )
    ).scalar_one()
    spend = float(
        (await s.execute(select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.user_id == user.id, LLMCall.created_at >= since))).scalar_one()
    )
    return {
        "plan": user.plan,
        "limits": limits,
        "drafts": int(drafts),
        "manual_runs": int(runs),
        "llm_usd": round(spend, 4),
        "drafts_left": max(0, int(limits["drafts_per_day"]) - int(drafts)),
        "runs_left": max(0, int(limits["manual_runs_per_day"]) - int(runs)),
        "ai_budget_left": max(0.0, round(limits["llm_usd_per_day"] - spend, 4)),
        # Quality gate: tailored applications in the last 7 days against the user's weekly cap.
        "week_applications": int(week),
        "weekly_cap": weekly_cap,
        "week_left": max(0, weekly_cap - int(week)),
    }


async def usage_for(user_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        user = await s.get(User, user_id)
        return await usage_today(s, user)


async def over_ai_budget(user_id: uuid.UUID) -> bool:
    """Past today's AI budget the agents keep working with the deterministic offline versions."""
    usage = await usage_for(user_id)
    return usage["ai_budget_left"] <= 0


async def enforce_run_limit(s: AsyncSession, user: User) -> None:
    usage = await usage_today(s, user)
    if usage["runs_left"] <= 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You've used today's {int(usage['limits']['manual_runs_per_day'])} on-demand runs on the {user.plan.title()} plan. "
            "Your agents keep watching for new jobs in the background.",
        )

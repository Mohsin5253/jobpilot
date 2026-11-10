"""Operator view: growth, health of the queue and the shared ingester, AI spend, and Pro requests."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import AdminDep, SessionDep
from app.config import PLAN_LIMITS
from app.models import AgentRun, Job, JobMatch, LLMCall, OutreachDraft, RunStatus, SourceTarget, User

router = APIRouter(prefix="/admin", tags=["admin"])


class PlanIn(BaseModel):
    email: str
    plan: str


class OrgIn(BaseModel):
    name: str


class OfficerIn(BaseModel):
    email: str


@router.get("/metrics")
async def metrics(_: AdminDep, session: SessionDep) -> dict:
    now = datetime.now(UTC)
    day, week = now - timedelta(days=1), now - timedelta(days=7)

    async def one(q):
        return (await session.execute(q)).scalar_one()

    real = User.is_demo.is_(False)
    users = {
        "total": await one(select(func.count()).where(real)),
        "new_7d": await one(select(func.count()).where(real, User.created_at >= week)),
        "active_1d": await one(select(func.count()).where(real, User.last_seen_at >= day)),
        "active_7d": await one(select(func.count()).where(real, User.last_seen_at >= week)),
        "pro": await one(select(func.count()).where(real, User.plan == "pro")),
        "demo_sessions_7d": await one(select(func.count()).where(User.is_demo.is_(True), User.created_at >= week)),
    }
    jobs = {
        "open": await one(select(func.count()).where(Job.last_seen_at >= now - timedelta(days=4))),
        "new_24h": await one(select(func.count()).where(Job.fetched_at >= day)),
        "matches_24h": await one(select(func.count()).where(JobMatch.created_at >= day)),
        "applications_7d": await one(select(func.count()).where(JobMatch.applied_at >= week)),
        "drafts_24h": await one(select(func.count()).where(OutreachDraft.created_at >= day)),
    }
    queue = dict((await session.execute(select(AgentRun.status, func.count()).where(AgentRun.status.in_([RunStatus.queued, RunStatus.running, RunStatus.resume_queued])).group_by(AgentRun.status))).all())
    runs_24h = dict((await session.execute(select(AgentRun.status, func.count()).where(AgentRun.created_at >= day).group_by(AgentRun.status))).all())
    sources = [
        {
            "source": src,
            "targets": n,
            "wanted": wanted,
            "failing": failing,
            "overdue": overdue,
            "last_fetch": last.isoformat() if last else None,
        }
        for src, n, wanted, failing, overdue, last in (
            await session.execute(
                select(
                    SourceTarget.source,
                    func.count(),
                    func.count().filter(SourceTarget.demand > 0),
                    func.count().filter(SourceTarget.failures > 0),
                    func.count().filter(SourceTarget.demand > 0, SourceTarget.next_due_at < now - timedelta(minutes=10)),
                    func.max(SourceTarget.last_fetched_at),
                )
                .where(SourceTarget.target != "*")
                .group_by(SourceTarget.source)
            )
        ).all()
    ]
    spend_24h = float(await one(select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.created_at >= day)))
    spend_by_agent = {a: round(float(c), 4) for a, c in (await session.execute(select(LLMCall.agent, func.sum(LLMCall.cost_usd)).where(LLMCall.created_at >= day).group_by(LLMCall.agent))).all()}
    pro_requests = [
        {"email": e, "name": n, "requested_at": at.isoformat()}
        for e, n, at in (
            await session.execute(select(User.email, User.name, User.pro_interest_at).where(User.pro_interest_at.is_not(None), User.plan != "pro").order_by(User.pro_interest_at))
        ).all()
    ]
    from app.services.outcomes import INTERVIEWED

    applied_total = await one(select(func.count()).where(JobMatch.applied_at.is_not(None)))
    interviews_total = await one(select(func.count()).where(JobMatch.applied_at.is_not(None), JobMatch.outcome.in_(INTERVIEWED)))
    jobs["interview_rate"] = round(100 * interviews_total / applied_total, 1) if applied_total else None
    jobs["applications_total"] = applied_total
    return {
        "generated_at": now.isoformat(),
        "users": users,
        "jobs": jobs,
        "queue": queue,
        "runs_24h": runs_24h,
        "sources": sources,
        "llm": {"usd_24h": round(spend_24h, 4), "by_agent": spend_by_agent, "usd_per_active_user": round(spend_24h / max(users["active_1d"], 1), 4)},
        "pro_requests": pro_requests,
    }


@router.post("/plan")
async def set_plan(body: PlanIn, _: AdminDep, session: SessionDep) -> dict:
    if body.plan not in PLAN_LIMITS:
        raise HTTPException(422, f"plan must be one of {', '.join(PLAN_LIMITS)}")
    user = (await session.execute(select(User).where(func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "No account with that email")
    user.plan = body.plan
    await session.commit()
    return {"email": user.email, "plan": user.plan}


@router.get("/orgs")
async def list_orgs(_: AdminDep, session: SessionDep) -> list[dict]:
    from app.models import Organization, OrgMember

    rows = (await session.execute(select(Organization).order_by(Organization.created_at))).scalars().all()
    out = []
    for o in rows:
        n = (await session.execute(select(func.count()).where(OrgMember.org_id == o.id, OrgMember.role == "student"))).scalar_one()
        officers = (await session.execute(select(User.email).join(OrgMember, OrgMember.user_id == User.id).where(OrgMember.org_id == o.id, OrgMember.role == "officer"))).scalars().all()
        out.append({"id": str(o.id), "name": o.name, "invite_code": o.invite_code, "students": n, "officers": officers})
    return out


@router.post("/orgs")
async def create_org(body: OrgIn, _: AdminDep, session: SessionDep) -> dict:
    """A college: students join with its invite code; officers see the placement-cell dashboard."""
    import re
    import secrets

    from app.models import Organization

    slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:60] + "-" + secrets.token_hex(2)
    org = Organization(name=body.name.strip(), slug=slug, invite_code=secrets.token_hex(3).upper())
    session.add(org)
    await session.commit()
    return {"id": str(org.id), "name": org.name, "invite_code": org.invite_code}


@router.post("/orgs/{org_id}/officers")
async def add_officer(org_id: str, body: OfficerIn, _: AdminDep, session: SessionDep) -> dict:
    import uuid

    from app.models import Organization, OrgMember

    org = await session.get(Organization, uuid.UUID(org_id))
    user = (await session.execute(select(User).where(func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    if org is None or user is None:
        raise HTTPException(404, "College or account not found")
    member = (await session.execute(select(OrgMember).where(OrgMember.user_id == user.id))).scalar_one_or_none()
    if member:
        member.org_id, member.role = org.id, "officer"
    else:
        session.add(OrgMember(org_id=org.id, user_id=user.id, role="officer"))
    await session.commit()
    return {"college": org.name, "officer": user.email}

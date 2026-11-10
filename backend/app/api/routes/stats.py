import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import Date, cast, func, select

from app.api.deps import SessionDep, UserDep
from app.config import settings
from app.models import AgentRun, DraftStatus, Job, JobMatch, Notification, QuestionStatus, SkillQuestion, LLMCall, OutreachDraft, Profile, Reminder, Stage
from app.schemas import AgentCost, DailyPoint, Overview, Preferences, ReminderOut, RunOut

router = APIRouter(tags=["stats"])


@router.get("/stats/overview", response_model=Overview)
async def overview(user: UserDep, session: SessionDep) -> Overview:
    uid = user.id
    now = datetime.now(UTC)
    since = now - timedelta(days=30)

    profile = (await session.execute(select(Profile).where(Profile.user_id == uid))).scalar_one_or_none()
    min_score = Preferences.model_validate(profile.preferences if profile else {}).min_score

    stage_counts = dict(
        (await session.execute(select(JobMatch.stage, func.count()).where(JobMatch.user_id == uid).group_by(JobMatch.stage))).all()
    )
    total, avg_score, strong = (
        await session.execute(
            select(func.count(), func.coalesce(func.avg(JobMatch.score), 0), func.count().filter(JobMatch.score >= min_score)).where(
                JobMatch.user_id == uid, JobMatch.stage != Stage.archived
            )
        )
    ).one()
    pending = (
        await session.execute(select(func.count()).where(OutreachDraft.user_id == uid, OutreachDraft.status == DraftStatus.pending))
    ).scalar_one()
    unread = (
        await session.execute(select(func.count()).where(Notification.user_id == uid, Notification.read_at.is_(None)))
    ).scalar_one()
    open_questions = (
        await session.execute(select(func.count()).where(SkillQuestion.user_id == uid, SkillQuestion.status == QuestionStatus.open))
    ).scalar_one()
    due = (
        await session.execute(
            select(func.count()).where(Reminder.user_id == uid, Reminder.dismissed_at.is_(None), Reminder.due_at <= now)
        )
    ).scalar_one()

    applied_total = sum(stage_counts.get(s, 0) for s in (Stage.applied, Stage.interview, Stage.offer, Stage.rejected))
    responded = sum(stage_counts.get(s, 0) for s in (Stage.interview, Stage.offer))
    response_rate = responded / applied_total if applied_total else 0.0

    cost_30d, runs_30d, avg_latency = (
        await session.execute(
            select(
                func.coalesce(func.sum(AgentRun.cost_usd), 0),
                func.count(),
                func.coalesce(func.avg(AgentRun.stats["active_ms"].as_float()), 0),
            ).where(AgentRun.user_id == uid, AgentRun.created_at >= since)
        )
    ).one()

    agent_rows = (
        await session.execute(
            select(
                LLMCall.agent,
                func.count(),
                func.coalesce(func.sum(LLMCall.cost_usd), 0),
                func.coalesce(func.avg(LLMCall.latency_ms), 0),
                func.coalesce(func.sum(LLMCall.input_tokens), 0),
                func.coalesce(func.sum(LLMCall.output_tokens), 0),
            )
            .where(LLMCall.user_id == uid, LLMCall.created_at >= since)
            .group_by(LLMCall.agent)
        )
    ).all()

    day = lambda col: cast(col, Date)  # noqa: E731
    found = dict(
        (await session.execute(select(day(JobMatch.created_at), func.count()).where(JobMatch.user_id == uid, JobMatch.created_at >= since).group_by(day(JobMatch.created_at)))).all()
    )
    applied = dict(
        (await session.execute(select(day(JobMatch.applied_at), func.count()).where(JobMatch.user_id == uid, JobMatch.applied_at >= since).group_by(day(JobMatch.applied_at)))).all()
    )
    costs = dict(
        (await session.execute(select(day(LLMCall.created_at), func.sum(LLMCall.cost_usd)).where(LLMCall.user_id == uid, LLMCall.created_at >= since).group_by(day(LLMCall.created_at)))).all()
    )
    daily = []
    for i in range(13, -1, -1):
        d = (now - timedelta(days=i)).date()
        daily.append(DailyPoint(day=d.isoformat(), found=found.get(d, 0), applied=applied.get(d, 0), cost_usd=float(costs.get(d, 0) or 0)))

    last = (
        await session.execute(select(AgentRun).where(AgentRun.user_id == uid).order_by(AgentRun.created_at.desc()).limit(1))
    ).scalar_one_or_none()

    return Overview(
        stage_counts={s.value: stage_counts.get(s.value, 0) for s in Stage},
        total_matches=total,
        strong_matches=strong,
        avg_score=round(float(avg_score), 1),
        pending_approvals=pending,
        open_questions=open_questions,
        unread_notifications=unread,
        due_reminders=due,
        response_rate=round(response_rate, 3),
        cost_30d=round(float(cost_30d), 4),
        runs_30d=runs_30d,
        avg_run_latency_ms=round(float(avg_latency), 0),
        agent_costs=[
            AgentCost(agent=a, calls=c, cost_usd=round(float(cost), 5), avg_latency_ms=round(float(lat), 0), input_tokens=int(i), output_tokens=int(o))
            for a, c, cost, lat, i, o in agent_rows
        ],
        daily=daily,
        last_run=RunOut.model_validate(last) if last else None,
        llm_mode=settings.llm_label,
        llm_models=list(settings.models) if settings.llm_enabled else [],
    )


@router.get("/reminders", response_model=list[ReminderOut])
async def reminders(user: UserDep, session: SessionDep) -> list[ReminderOut]:
    rows = (
        await session.execute(
            select(Reminder, Job.company, Job.title)
            .join(JobMatch, JobMatch.id == Reminder.match_id)
            .join(Job, Job.id == JobMatch.job_id)
            .where(Reminder.user_id == user.id, Reminder.dismissed_at.is_(None), Reminder.due_at <= datetime.now(UTC))
            .order_by(Reminder.due_at)
        )
    ).all()
    return [ReminderOut(**ReminderOut.model_validate(r).model_dump(exclude={"company", "title"}), company=c, title=t) for r, c, t in rows]


@router.post("/reminders/{reminder_id}/dismiss", status_code=204)
async def dismiss(reminder_id: uuid.UUID, user: UserDep, session: SessionDep) -> None:
    r = (await session.execute(select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user.id))).scalar_one_or_none()
    if r:
        r.dismissed_at = datetime.now(UTC)
        await session.commit()

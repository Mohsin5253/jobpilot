"""Tracker: keeps the Kanban board honest and raises follow-up reminders 7 days after applying."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.agents.common import PipelineState, agent_step, bump_stats, load_profile
from app.config import settings
from app.services.mailer import send_system_email
from app.db import session_scope
from app.models import AgentRun, Job, JobMatch, Notification, Reminder, Stage, User


async def follow_up_sweep(user_id: uuid.UUID | None = None) -> int:
    """Create a reminder for every applied job whose follow-up date has passed. Idempotent."""
    now = datetime.now(UTC)
    async with session_scope() as s:
        q = (
            select(JobMatch.id, JobMatch.user_id, JobMatch.follow_up_at, Job.company, Job.title)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.stage == Stage.applied, JobMatch.follow_up_at.is_not(None), JobMatch.follow_up_at <= now)
        )
        if user_id:
            q = q.where(JobMatch.user_id == user_id)
        due = (await s.execute(q)).all()
        # The feedback loop: 21 days after applying with no outcome recorded, ask whether it went silent.
        quiet_q = (
            select(JobMatch.id, JobMatch.user_id, JobMatch.applied_at, Job.company, Job.title)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.stage == Stage.applied, JobMatch.outcome == "none", JobMatch.applied_at <= now - timedelta(days=21))
        )
        if user_id:
            quiet_q = quiet_q.where(JobMatch.user_id == user_id)
        quiet = (await s.execute(quiet_q)).all()
        if quiet:
            await s.execute(
                insert(Reminder)
                .values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "user_id": r.user_id,
                            "match_id": r.id,
                            "kind": "outcome_check",
                            "message": f"3 weeks since you applied to {r.company} ({r.title}). Did they reply? Mark it so Insights can learn.",
                            "due_at": now,
                        }
                        for r in quiet
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_reminder_match_kind")
            )
        if not due:
            return 0
        result = await s.execute(
            insert(Reminder)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "user_id": r.user_id,
                        "match_id": r.id,
                        "kind": "follow_up",
                        "message": f"No reply from {r.company} on {r.title} yet — send a short follow-up.",
                        "due_at": r.follow_up_at,
                    }
                    for r in due
                ]
            )
            .on_conflict_do_nothing(constraint="uq_reminder_match_kind")
            .returning(Reminder.id)
        )
        return len(result.all())


async def email_new_matches(state: PipelineState) -> int:
    """Email alert: the new matches this run found, if the user turned alerts on and SMTP is configured."""
    if not settings.smtp_enabled:
        return 0
    _, _, prefs = await load_profile(state["user_id"])
    if not prefs.email_alerts:
        return 0
    async with session_scope() as s:
        run = await s.get(AgentRun, uuid.UUID(state["run_id"]))
        user = await s.get(User, uuid.UUID(state["user_id"]))
        rows = (
            await s.execute(
                select(Notification).where(
                    Notification.user_id == user.id, Notification.kind == "new_match", Notification.created_at >= run.started_at
                )
            )
        ).scalars().all()
    if not rows:
        return 0
    body = "New jobs that fit your profile:\n\n" + "\n\n".join(f"• {n.title}\n  {n.body}" for n in rows)
    body += "\n\nOpen JobPilot to review the tailored resume and draft, then approve to apply."
    sent = await send_system_email(user.email, f"JobPilot: {len(rows)} new match{'es' if len(rows) > 1 else ''}", body)
    return len(rows) if sent else 0


async def run_tracker(state: PipelineState) -> dict:
    async with agent_step(state, "tracker") as step:
        user_id = uuid.UUID(state["user_id"])
        created = await follow_up_sweep(user_id)
        async with session_scope() as s:
            counts = dict(
                (await s.execute(select(JobMatch.stage, func.count()).where(JobMatch.user_id == user_id).group_by(JobMatch.stage))).all()
            )
        board = " · ".join(f"{k}: {counts.get(k, 0)}" for k in (Stage.found, Stage.shortlisted, Stage.applied, Stage.interview, Stage.offer))
        alerted = await email_new_matches(state)
        step.detail = f"{created} new follow-up reminder(s) · {board}" + (f" · emailed you {alerted} new match(es)" if alerted else "")
        await bump_stats(state["run_id"], reminders=created)
        return {"done": ["tracker"]}

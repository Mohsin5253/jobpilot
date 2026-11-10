"""Human-in-the-loop. The approval gate pauses the graph (LangGraph interrupt) until every draft from
this run has been approved or rejected in the UI; the dispatcher then performs the outside-world
actions for approved drafts only."""

import uuid
from datetime import UTC, datetime

from langgraph.types import interrupt
from sqlalchemy import select, update

from app.agents.common import PipelineState, _patch_step, agent_step, bump_stats
from app.db import session_scope
from app.logging import log
from app.models import AgentRun, DraftStatus, JobMatch, OutreachDraft, RunStatus
from app.services.applications import send_application
from app.services.mailer import user_sender


async def pending_drafts(run_id: str) -> list[str]:
    async with session_scope() as s:
        rows = await s.execute(
            select(OutreachDraft.id).where(OutreachDraft.run_id == uuid.UUID(run_id), OutreachDraft.status == DraftStatus.pending)
        )
        return [str(x) for x in rows.scalars().all()]


async def run_approval_gate(state: PipelineState) -> dict:
    # This node re-executes from the top when the graph resumes, so everything before interrupt()
    # must be idempotent: it only reads the queue and flags the run.
    pending = await pending_drafts(state["run_id"])
    run_id = uuid.UUID(state["run_id"])
    if pending:
        await _patch_step(run_id, "approval", status="waiting", detail=f"{len(pending)} draft(s) waiting for your review")
        async with session_scope() as s:
            await s.execute(
                update(AgentRun)
                .where(AgentRun.id == uuid.UUID(state["run_id"]))
                .values(status=RunStatus.awaiting_approval, current_step="approval")
            )
        interrupt({"pending_draft_ids": pending, "message": "Review drafts in the approval queue"})
    await _patch_step(run_id, "approval", status="completed", ended_at=datetime.now(UTC).isoformat(), detail="All drafts reviewed")
    return {"done": ["approval"]}


async def run_dispatch(state: PipelineState) -> dict:
    async with agent_step(state, "dispatch") as step:
        async with session_scope() as s:
            rows = (
                await s.execute(
                    select(OutreachDraft, JobMatch)
                    .join(JobMatch, JobMatch.id == OutreachDraft.match_id)
                    .where(OutreachDraft.run_id == uuid.UUID(state["run_id"]), OutreachDraft.status == DraftStatus.approved)
                )
            ).all()
        sent = manual = 0
        connected = bool(rows) and await user_sender(uuid.UUID(state["user_id"])) is not None  # the user's own mailbox
        for draft, match in rows:
            to = draft.to_email or match.job.recruiter_email
            if connected and to:
                try:
                    await send_application(draft.id, wait=True)  # sends are spaced; the background job waits
                except Exception as exc:  # leave it approved-but-unsent; user can send manually
                    log.warning("dispatch.send_failed", draft_id=str(draft.id), error=str(exc))
                    manual += 1
                    continue
                sent += 1
            else:
                manual += 1
        step.detail = f"{len(rows)} approved · {sent} emailed · {manual} ready to send manually (copy / mailto / LinkedIn)"
        await bump_stats(state["run_id"], approved=len(rows), sent=sent)
        return {"done": ["dispatch"]}

import operator
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from sqlalchemy import select, update

from app.db import session_scope
from app.llm import CallContext
from app.logging import log
from app.models import AgentRun, Profile
from app.schemas import Preferences, ResumeData
from app.tracing import observe


class PipelineState(TypedDict, total=False):
    """Shared state the supervisor routes on. IDs are strings so checkpoints stay JSON-friendly."""

    run_id: str
    user_id: str
    next: str
    done: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    new_job_ids: list[str]
    rescore_match_ids: list[str]  # set on runs started by answering skill questions
    direct: bool  # "Prepare application" runs: tailor + draft the given shortlist_ids only
    force_research: bool  # "Research now": skip the Researcher's cooldown
    refresh: bool  # frequent background refresh: only fetch sources whose polite gap has passed
    match_ids: list[str]
    question_ids: list[str]
    shortlist_ids: list[str]
    tailored_ids: list[str]
    draft_ids: list[str]


def ctx_of(state: PipelineState) -> CallContext:
    return CallContext(user_id=uuid.UUID(state["user_id"]), run_id=uuid.UUID(state["run_id"]))


async def load_profile(user_id: str) -> tuple[Profile, ResumeData, Preferences]:
    async with session_scope() as s:
        profile = (await s.execute(select(Profile).where(Profile.user_id == uuid.UUID(user_id)))).scalar_one()
        return profile, ResumeData.model_validate(profile.resume or {}), Preferences.model_validate(profile.preferences or {})


async def _patch_step(run_id: uuid.UUID, agent: str, **fields) -> None:
    async with session_scope() as s:
        run = (await s.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())).scalar_one()
        steps = [dict(x) for x in run.steps or []]
        for st in steps:
            if st["agent"] == agent:
                st.update(fields)
                break
        else:
            steps.append({"agent": agent, "status": "pending", "detail": "", **fields})
        await s.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(steps=steps, current_step=agent if fields.get("status") == "running" else run.current_step)
        )


class StepHandle:
    def __init__(self) -> None:
        self.detail = ""


@asynccontextmanager
async def agent_step(state: PipelineState, agent: str):
    """Records the step on the run (for the live timeline in the UI) and opens a trace span."""
    run_id = uuid.UUID(state["run_id"])
    handle = StepHandle()
    now = lambda: datetime.now(UTC).isoformat()  # noqa: E731
    await _patch_step(run_id, agent, status="running", started_at=now(), ended_at=None, detail="")
    log.info("agent.start", agent=agent, run_id=str(run_id))
    with observe(f"agent.{agent}", as_type="agent", metadata={"run_id": str(run_id)}) as span:
        try:
            yield handle
        except Exception as exc:
            await _patch_step(run_id, agent, status="failed", ended_at=now(), detail=str(exc)[:500])
            span.update(level="ERROR", status_message=str(exc)[:500])
            log.exception("agent.failed", agent=agent, run_id=str(run_id))
            raise
        await _patch_step(run_id, agent, status="completed", ended_at=now(), detail=handle.detail)
        span.update(output=handle.detail)
        log.info("agent.done", agent=agent, run_id=str(run_id), detail=handle.detail)


async def mark_skipped(state: PipelineState, agent: str, reason: str) -> None:
    await _patch_step(uuid.UUID(state["run_id"]), agent, status="skipped", detail=reason)


async def bump_stats(run_id: str, **values: int) -> None:
    async with session_scope() as s:
        run = (await s.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(run_id)).with_for_update())).scalar_one()
        stats = dict(run.stats or {})
        stats.update(values)
        run.stats = stats

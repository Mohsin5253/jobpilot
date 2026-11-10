"""Run lifecycle: enqueue, claim (Postgres SKIP LOCKED queue), execute / resume the LangGraph pipeline."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import build_graph
from app.config import settings
from app.db import session_scope
from app.logging import log
from app.models import AgentRun, RunStatus
from app.tracing import flush, observe

ACTIVE = (RunStatus.queued, RunStatus.running, RunStatus.resume_queued)

_pool: AsyncConnectionPool | None = None
_graph = None


async def get_graph():
    """Compiled graph with a Postgres checkpointer (one pool per process)."""
    global _pool, _graph
    if _graph is None:
        _pool = AsyncConnectionPool(
            conninfo=settings.psycopg_conninfo,
            max_size=10,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await _pool.open()
        saver = AsyncPostgresSaver(_pool)
        await saver.setup()
        _graph = build_graph(saver)
    return _graph


async def close_graph() -> None:
    global _pool, _graph
    if _pool is not None:
        await _pool.close()
    _pool, _graph = None, None


async def enqueue_run(s: AsyncSession, user_id: uuid.UUID, trigger: str = "manual", params: dict | None = None) -> tuple[AgentRun, bool]:
    """Returns (run, created). One active run per user at a time."""
    existing = (
        await s.execute(
            select(AgentRun).where(AgentRun.user_id == user_id, AgentRun.status.in_(ACTIVE)).order_by(AgentRun.created_at.desc())
        )
    ).scalar_one_or_none()
    if existing:
        return existing, False
    run = AgentRun(user_id=user_id, trigger=trigger, status=RunStatus.queued, steps=[], stats={}, params=params or {})
    s.add(run)
    await s.flush()
    return run, True


async def request_resume(s: AsyncSession, run_id: uuid.UUID) -> None:
    await s.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.status == RunStatus.awaiting_approval)
        .values(status=RunStatus.resume_queued)
    )


CLAIM_SQL = text(
    """
    WITH c AS (
        SELECT id FROM agent_runs
        WHERE status IN ('queued', 'resume_queued')
           OR (status = 'running' AND locked_at < now() - make_interval(mins => :stale))
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE agent_runs a
       SET status = 'running', locked_by = :worker, locked_at = now(), attempts = a.attempts + 1,
           started_at = COALESCE(a.started_at, now())
      FROM c WHERE a.id = c.id
    RETURNING a.id, a.user_id, a.attempts
    """
)


async def claim_next(worker_id: str):
    async with session_scope() as s:
        row = (await s.execute(CLAIM_SQL, {"worker": worker_id, "stale": settings.run_lock_timeout_minutes})).first()
        return row


async def _finish(run_id: uuid.UUID, **values) -> None:
    from app.services.events import publish

    async with session_scope() as s:
        user_id = (
            await s.execute(
                update(AgentRun).where(AgentRun.id == run_id).values(locked_by=None, locked_at=None, **values).returning(AgentRun.user_id)
            )
        ).scalar_one_or_none()
        if user_id:
            await publish(s, user_id, "run_updated", run_id=str(run_id), status=str(values.get("status", "")))


async def _add_active_time(run_id: uuid.UUID, ms: int) -> None:
    """Latency excludes the hours a run may spend paused for approval: only time spent executing counts."""
    async with session_scope() as s:
        await s.execute(
            text("UPDATE agent_runs SET stats = jsonb_set(stats, '{active_ms}', to_jsonb(COALESCE((stats->>'active_ms')::int, 0) + :ms)) WHERE id = :id"),
            {"ms": ms, "id": run_id},
        )


async def execute_run(run_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Start, resume or retry a run. Which one is decided by the checkpoint, not by the caller:
    no checkpoint -> fresh start; paused at the approval interrupt -> resume; mid-graph -> continue."""
    graph = await get_graph()
    config = {"configurable": {"thread_id": str(run_id)}, "recursion_limit": 50}
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        async with session_scope() as s:
            params = (await s.execute(select(AgentRun.params).where(AgentRun.id == run_id))).scalar_one() or {}
        payload = {"run_id": str(run_id), "user_id": str(user_id), "done": [], "errors": [], **params}
        mode = "start"
    elif any(t.interrupts for t in snapshot.tasks):
        payload, mode = Command(resume={"resumed_at": datetime.now(UTC).isoformat()}), "resume"
    elif snapshot.next:
        payload, mode = None, "continue"
    else:
        await _finish(run_id, status=RunStatus.completed, finished_at=datetime.now(UTC), current_step=None)
        return RunStatus.completed

    log.info("run.execute", run_id=str(run_id), mode=mode)
    started = time.perf_counter()
    try:
        with observe("pipeline.run", as_type="chain", metadata={"run_id": str(run_id), "mode": mode}):
            await graph.ainvoke(payload, config)
        after = await graph.aget_state(config)
    except Exception as exc:
        log.exception("run.failed", run_id=str(run_id))
        await _finish(run_id, status=RunStatus.failed, error=f"{type(exc).__name__}: {exc}"[:2000], finished_at=datetime.now(UTC))
        return RunStatus.failed
    finally:
        flush()
        await _add_active_time(run_id, int((time.perf_counter() - started) * 1000))

    if after.next:  # paused at the approval gate
        await _finish(run_id, status=RunStatus.awaiting_approval, current_step="approval")
        return RunStatus.awaiting_approval
    await _finish(run_id, status=RunStatus.completed, finished_at=datetime.now(UTC), current_step=None, error=None)
    await prune_empty_refresh(run_id)
    return RunStatus.completed


async def enqueue_scheduled_runs() -> int:
    """Hourly: queue the daily run for users whose chosen hour is now. A transaction-scoped advisory
    lock means only one replica does this even when several workers run the scheduler."""
    now = datetime.now(UTC)
    created = 0
    async with session_scope() as s:
        got_lock = (await s.execute(text("SELECT pg_try_advisory_xact_lock(724001)"))).scalar()
        if not got_lock:
            return 0
        rows = (
            await s.execute(
                text(
                    """
                    SELECT p.user_id FROM profiles p
                    WHERE p.resume_text <> ''
                      AND COALESCE((p.preferences->>'daily_runs_enabled')::boolean, true)
                      AND COALESCE((p.preferences->>'daily_run_hour_utc')::int, 3) = :hour
                      AND NOT EXISTS (
                        SELECT 1 FROM agent_runs r
                        WHERE r.user_id = p.user_id AND r.trigger = 'scheduled' AND r.created_at > :since)
                    """
                ),
                {"hour": now.hour, "since": now - timedelta(hours=20)},
            )
        ).scalars().all()
        for uid in rows:
            _, was_created = await enqueue_run(s, uid, trigger="scheduled")
            created += was_created
    if created:
        log.info("scheduler.enqueued", count=created)
    return created


async def prune_empty_refresh(run_id: uuid.UUID) -> bool:
    """Refresh runs that found nothing new are noise in the run history: drop them and their checkpoint."""
    async with session_scope() as s:
        run = await s.get(AgentRun, run_id)
        if not run or run.trigger != "refresh" or run.status != RunStatus.completed or (run.stats or {}).get("new_jobs"):
            return False
        await s.delete(run)
    graph = await get_graph()
    try:
        await graph.checkpointer.adelete_thread(str(run_id))
    except Exception as exc:  # pruning is housekeeping; never fail a run over it
        log.warning("runs.prune_checkpoint_failed", error=str(exc))
    return True


async def enqueue_research_runs() -> int:
    """Continuous research: every user with research on gets a fresh run once their interval has
    passed since their last run of any kind (so a daily run also counts). Advisory-locked like the
    daily sweep, and enqueue_run keeps it to one active run per user."""
    now = datetime.now(UTC)
    created = 0
    async with session_scope() as s:
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(724002)"))).scalar():
            return 0
        rows = (
            await s.execute(
                text(
                    """
                    SELECT p.user_id FROM profiles p
                    WHERE p.resume_text <> ''
                      AND COALESCE((p.preferences->>'research_enabled')::boolean, true)
                      AND NOT EXISTS (
                        SELECT 1 FROM agent_runs r
                        WHERE r.user_id = p.user_id
                          AND r.created_at > :now - make_interval(hours => COALESCE((p.preferences->>'research_interval_hours')::int, 6)))
                    """
                ),
                {"now": now},
            )
        ).scalars().all()
        for uid in rows:
            _, was_created = await enqueue_run(s, uid, trigger="research")
            created += was_created
    if created:
        log.info("scheduler.research_enqueued", count=created)
    return created

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.models import AgentRun, LLMCall, Profile, RunStatus
from app.schemas import LLMCallOut, RunDetail, RunOut
from app.services.ratelimit import hit
from app.services.runs import enqueue_run
from app.services.usage import enforce_run_limit

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(user: UserDep, session: SessionDep, request: Request, response: Response) -> AgentRun:
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None or not profile.resume_text:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload your resume before running the agents")
    await hit("run", str(user.id))
    await enforce_run_limit(session, user)
    run, created = await enqueue_run(session, user.id, trigger="manual")
    await session.commit()
    await session.refresh(run)
    if not created:
        response.status_code = status.HTTP_200_OK
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(user: UserDep, session: SessionDep, limit: int = Query(default=20, le=100)) -> list[AgentRun]:
    rows = await session.execute(
        select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.created_at.desc()).limit(limit)
    )
    return list(rows.scalars().all())


async def _get(session, user_id, run_id) -> AgentRun:
    run = (await session.execute(select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, user: UserDep, session: SessionDep) -> RunDetail:
    run = await _get(session, user.id, run_id)
    calls = (await session.execute(select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.created_at))).scalars().all()
    return RunDetail(**RunOut.model_validate(run).model_dump(), calls=[LLMCallOut.model_validate(c) for c in calls])


@router.post("/{run_id}/retry", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_run(run_id: uuid.UUID, user: UserDep, session: SessionDep) -> AgentRun:
    """Re-queue a failed run. The worker continues from the last checkpointed agent, not from scratch."""
    run = await _get(session, user.id, run_id)
    if run.status != RunStatus.failed:
        raise HTTPException(409, "Only failed runs can be retried")
    run.status = RunStatus.queued
    run.error = None
    run.finished_at = None
    await session.commit()
    await session.refresh(run)
    return run

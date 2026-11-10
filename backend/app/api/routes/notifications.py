from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from app.api.deps import SessionDep, UserDep
from app.config import settings
from app.models import Notification, Profile
from app.schemas import NotificationOut, Preferences, ResearchState, RunOut
from app.services.runs import enqueue_run

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(user: UserDep, session: SessionDep, limit: int = 30) -> list[Notification]:
    rows = await session.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(min(limit, 100))
    )
    return list(rows.scalars())


class ReadIn(BaseModel):
    ids: list[str] | None = None  # None = mark everything read


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(body: ReadIn, user: UserDep, session: SessionDep) -> None:
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    await session.execute(q.values(read_at=datetime.now(UTC)))
    await session.commit()


@router.get("/research", response_model=ResearchState)
async def research_state(user: UserDep, session: SessionDep) -> ResearchState:
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    r = profile.research or {}
    prefs = Preferences.model_validate(profile.preferences or {})
    last = datetime.fromisoformat(r["last_research_at"]) if r.get("last_research_at") else None
    return ResearchState(
        last_research_at=last,
        checked=len(r.get("checked", [])),
        added=list(reversed(r.get("added", [])))[:50],
        next_run_at=(last + timedelta(hours=prefs.research_interval_hours)) if last and prefs.research_enabled else None,
    )


@router.post("/research/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def research_now(user: UserDep, session: SessionDep) -> RunOut:
    """Run the full agent team now, with the Researcher searching for new companies right away."""
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    if not profile.resume_text:
        raise HTTPException(409, "Upload your resume first")
    from app.services.usage import enforce_run_limit

    await enforce_run_limit(session, user)
    run, created = await enqueue_run(session, user.id, trigger="research", params={"force_research": True})
    if not created:
        raise HTTPException(409, "Agents are already running — results will show up when this run finishes")
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.get("/config")
async def config(user: UserDep) -> dict:
    from app.services.mailer import user_sender

    sender = await user_sender(user.id)
    return {
        # "Approve & send" works once *this user* has connected their own mailbox.
        "smtp_enabled": sender is not None,
        "smtp_from": sender.from_email if sender else None,
        "system_mail_enabled": settings.smtp_enabled,
        "hunter_enabled": bool(settings.hunter_api_key),
        "jsearch_enabled": bool(settings.jsearch_api_key),
        "adzuna_enabled": bool(settings.adzuna_app_id and settings.adzuna_app_key),
        "llm": settings.llm_label,
    }

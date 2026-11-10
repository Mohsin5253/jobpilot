"""One-click demo accounts for the landing page.

Each visitor gets a private, throwaway account (deleted after settings.demo_ttl_hours) that is a copy of a
showcase account (settings.demo_template_email): its resume, real matched jobs, tailored resumes and
drafts. Nothing is generated per visitor, so a thousand demo clicks cost no LLM calls. Demo accounts
can't send mail, connect mail or change credentials, and the background agents leave them alone.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.matcher import ensure_profile_embedding
from app.config import settings
from app.models import JobMatch, OutreachDraft, Profile, Stage, TailoredResume, User
from app.resume_parser import extract_text, heuristic_parse
from app.schemas import Preferences
from app.security import hash_password

SAMPLE = Path(__file__).resolve().parents[2] / "evals" / "data" / "sample_resume.md"
CLONE_MATCHES = 30


async def create_demo_user(s: AsyncSession) -> User:
    now = datetime.now(UTC)
    user = User(
        email=f"demo-{secrets.token_hex(6)}@demo.jobpilot.app",
        name="Demo student",
        password_hash=hash_password(secrets.token_urlsafe(24)),  # nobody knows it: sign-in is the demo link only
        is_demo=True,
        expires_at=now + timedelta(hours=settings.demo_ttl_hours),
    )
    s.add(user)
    await s.flush()
    from app.services.consent import grant

    await grant(s, user.id, "core")

    template = (
        await s.execute(select(User).where(User.email == settings.demo_template_email.lower(), User.is_demo.is_(False)))
    ).scalar_one_or_none()
    source = (await s.execute(select(Profile).where(Profile.user_id == template.id))).scalar_one_or_none() if template else None
    quiet = {"research_enabled": False, "daily_runs_enabled": False, "email_alerts": False}

    if source is None or not source.resume_text:
        # No showcase account yet: the sample resume, parsed without an LLM.
        text = extract_text(SAMPLE.name, SAMPLE.read_bytes())
        resume = heuristic_parse(text)
        profile = Profile(
            user_id=user.id, resume_filename="sample_resume.md", resume_text=text, resume=resume.model_dump(),
            preferences={**Preferences().model_dump(), **quiet},
        )
        s.add(profile)
        await s.flush()
        await s.commit()
        await ensure_profile_embedding(profile.id, resume)
        return user

    s.add(
        Profile(
            user_id=user.id, resume_filename=source.resume_filename, resume_text=source.resume_text, resume=source.resume,
            preferences={**(source.preferences or {}), **quiet}, embedding=source.embedding, research={},
        )
    )
    matches = (
        await s.execute(
            select(JobMatch).where(JobMatch.user_id == template.id, JobMatch.stage != Stage.archived).order_by(JobMatch.score.desc()).limit(CLONE_MATCHES)
        )
    ).unique().scalars().all()
    ids = {m.id: uuid.uuid4() for m in matches}
    fields = ("job_id", "score", "semantic_score", "skill_score", "llm_score", "strengths", "gaps", "explanation", "stage", "applied_at", "follow_up_at", "notes")
    for m in matches:
        s.add(JobMatch(id=ids[m.id], user_id=user.id, **{f: getattr(m, f) for f in fields}))
    await s.flush()
    for t in (await s.execute(select(TailoredResume).where(TailoredResume.match_id.in_(ids)))).scalars():
        s.add(TailoredResume(match_id=ids[t.match_id], bullets=t.bullets, guard_report=t.guard_report, model=t.model))
    # The newest draft of each kind per job (a re-prepared job keeps only its latest application and referral).
    latest: dict[tuple, OutreachDraft] = {}
    for d in (await s.execute(select(OutreachDraft).where(OutreachDraft.match_id.in_(ids)).order_by(OutreachDraft.created_at))).unique().scalars():
        latest[(d.match_id, d.kind)] = d
    for d in latest.values():
        s.add(
            OutreachDraft(
                user_id=user.id, match_id=ids[d.match_id], kind=d.kind, subject=d.subject, email_body=d.email_body, linkedin_note=d.linkedin_note,
                to_email=d.to_email, contact_id=d.contact_id, cc_email=d.cc_email, status="pending",
            )
        )
    await s.commit()
    return user


async def prune_demo_users() -> int:
    from app.db import session_scope

    async with session_scope() as s:
        result = await s.execute(delete(User).where(User.is_demo.is_(True), User.expires_at < datetime.now(UTC)))
        return result.rowcount or 0

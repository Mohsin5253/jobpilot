import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.agents.matcher import ensure_profile_embedding
from app.api.deps import SessionDep, UserDep
from app.models import Job, JobMatch, Profile, QuestionStatus, SkillQuestion, Stage
from app.schemas import AdditionalSkill, AnswersIn, AnswersOut, QuestionOut, ResumeData
from app.services.runs import enqueue_run

router = APIRouter(prefix="/questions", tags=["skill questions"])

MIN_DETAILS = 15  # a "yes" needs a sentence the Tailor can actually use


@router.get("", response_model=list[QuestionOut])
async def list_questions(user: UserDep, session: SessionDep, status: str = "open") -> list[QuestionOut]:
    qs = (
        await session.execute(
            select(SkillQuestion).where(SkillQuestion.user_id == user.id, SkillQuestion.status == status).order_by(SkillQuestion.created_at.desc())
        )
    ).scalars().all()
    all_ids = {uuid.UUID(m) for q in qs for m in q.match_ids}
    labels: dict[str, str] = {}
    if all_ids:
        rows = await session.execute(
            select(JobMatch.id, Job.title, Job.company).join(Job, Job.id == JobMatch.job_id).where(JobMatch.id.in_(all_ids))
        )
        labels = {str(i): f"{t} @ {c}" for i, t, c in rows}
    out = [
        QuestionOut(
            **QuestionOut.model_validate(q).model_dump(exclude={"unlocks", "jobs"}),
            unlocks=len(q.match_ids),
            jobs=[labels[m] for m in q.match_ids if m in labels][:4],
        )
        for q in qs
    ]
    return sorted(out, key=lambda q: q.unlocks, reverse=True)


@router.post("/answers", response_model=AnswersOut)
async def answer(body: AnswersIn, user: UserDep, session: SessionDep) -> AnswersOut:
    ids = [a.id for a in body.answers]
    qs = {
        q.id: q
        for q in (
            await session.execute(select(SkillQuestion).where(SkillQuestion.id.in_(ids), SkillQuestion.user_id == user.id))
        ).scalars()
    }
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    resume = ResumeData.model_validate(profile.resume or {})
    now = datetime.now(UTC)
    added: list[str] = []
    unlock: set[str] = set()
    answered = 0

    for a in body.answers:
        q = qs.get(a.id)
        if q is None or q.status != QuestionStatus.open:
            continue
        details = a.details.strip()
        if a.has_skill:
            if len(details) < MIN_DETAILS:
                raise HTTPException(422, f"Add a sentence about how you used {q.skill} — the Tailor can only use what you write.")
            q.status = QuestionStatus.yes
            if q.skill.lower() not in {s.lower() for s in resume.skills}:
                resume.skills.append(q.skill)
            resume.additional.append(AdditionalSkill(skill=q.skill, details=details))
            added.append(q.skill)
            unlock.update(q.match_ids)
        else:
            q.status = QuestionStatus.no
        q.answer = details
        q.answered_at = now
        answered += 1

    run_id = None
    rechecking = 0
    if added:
        profile.resume = resume.model_dump()
        flag_modified(profile, "resume")
        # Only jobs still on the "found" column and still listed are worth re-checking.
        live_since = now - timedelta(days=4)
        candidates = (
            await session.execute(
                select(JobMatch.id)
                .join(Job, Job.id == JobMatch.job_id)
                .where(
                    JobMatch.id.in_([uuid.UUID(m) for m in unlock]),
                    JobMatch.user_id == user.id,
                    JobMatch.stage == Stage.found,
                    Job.last_seen_at >= live_since,
                )
            )
        ).scalars().all()
        rechecking = len(candidates)
        if candidates:
            run, created = await enqueue_run(session, user.id, trigger="skills", params={"rescore_match_ids": [str(c) for c in candidates]})
            run_id = run.id if created else None
            if not created:
                rechecking = 0  # another run is in flight; the next daily run re-scores with the new skills
    await session.commit()
    if added:
        await ensure_profile_embedding(profile.id, resume)
    return AnswersOut(answered=answered, skills_added=added, rematch_run_id=run_id, rechecking_jobs=rechecking)


@router.post("/{question_id}/dismiss", status_code=204)
async def dismiss(question_id: uuid.UUID, user: UserDep, session: SessionDep) -> None:
    q = (
        await session.execute(select(SkillQuestion).where(SkillQuestion.id == question_id, SkillQuestion.user_id == user.id))
    ).scalar_one_or_none()
    if q and q.status == QuestionStatus.open:
        q.status = QuestionStatus.dismissed
        q.answered_at = datetime.now(UTC)
        await session.commit()

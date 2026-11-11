import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, UserDep
from app.config import settings
from app.models import CompanyContact, DraftStatus, Job, JobMatch, OutreachDraft, Profile, ProofLink, Stage, TailoredResume
from app.llm import CallContext
from app.schemas import BulletDecision, ContactOut, ContactsOut, DraftOut, JobOut, MatchDetail, MatchOut, MatchPage, MatchUpdate, ResumeData, RunOut, TailoredOut
from app.services.contacts import find_contacts, rank
from app.services import resume_doc
from app.services.runs import enqueue_run

router = APIRouter(prefix="/matches", tags=["matches"])

ACTIVE_STAGES = (Stage.applied, Stage.interview, Stage.offer)


DRAFT_FLAGS = ("has_tailored", "pending_draft", "approved_draft", "sent_draft", "proof_views", "proof_last_viewed_at")


def to_out(m: JobMatch, has_tailored: bool = False, pending_draft: bool = False, approved_draft: bool = False, sent_draft: bool = False) -> MatchOut:
    data = {c: getattr(m, c) for c in MatchOut.model_fields if c != "job" and c not in DRAFT_FLAGS}
    return MatchOut(**data, job=JobOut.model_validate(m.job), has_tailored=has_tailored, pending_draft=pending_draft, approved_draft=approved_draft, sent_draft=sent_draft)


def to_out_loaded(m: JobMatch) -> MatchOut:
    """For a match loaded with its tailored resume and drafts."""
    status = {d.status for d in m.drafts}
    return to_out(m, m.tailored is not None, DraftStatus.pending in status, DraftStatus.approved in status, DraftStatus.sent in status)


async def _get(session, user_id: uuid.UUID, match_id: uuid.UUID) -> JobMatch:
    m = (
        await session.execute(
            select(JobMatch)
            .where(JobMatch.id == match_id, JobMatch.user_id == user_id)
            .options(selectinload(JobMatch.tailored), selectinload(JobMatch.drafts))
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Match not found")
    return m


@router.get("", response_model=MatchPage)
async def list_matches(
    user: UserDep,
    session: SessionDep,
    stage: list[str] | None = Query(default=None),
    min_score: float = 0,
    q: str | None = None,
    remote: bool | None = None,
    source: str | None = None,
    track: Literal["technical", "non_technical"] | None = None,
    include_closed: bool = False,
    sort: Literal["score", "recent", "posted"] = "score",
    limit: int = Query(default=50, le=500),
    offset: int = 0,
) -> MatchPage:
    has_tailored = exists().where(TailoredResume.match_id == JobMatch.id)
    pending = exists().where(OutreachDraft.match_id == JobMatch.id, OutreachDraft.status == DraftStatus.pending)
    # The tracker splits Applied into Approved (waiting in your mail app) and Sent.
    approved = exists().where(OutreachDraft.match_id == JobMatch.id, OutreachDraft.status == DraftStatus.approved)
    sent = exists().where(OutreachDraft.match_id == JobMatch.id, OutreachDraft.status == DraftStatus.sent)
    base = select(JobMatch, has_tailored.label("ht"), pending.label("pd"), approved.label("ad"), sent.label("sd")).join(Job, Job.id == JobMatch.job_id).where(
        JobMatch.user_id == user.id, JobMatch.score >= min_score
    )
    if stage:
        base = base.where(JobMatch.stage.in_(stage))
    else:
        base = base.where(JobMatch.stage != Stage.archived)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(or_(Job.title.ilike(like), Job.company.ilike(like), Job.location.ilike(like)))
    if remote is not None:
        base = base.where(Job.remote.is_(remote))
    if source:
        base = base.where(Job.source == source)
    if track:
        base = base.where(Job.track == track)
    if not include_closed:
        # Not listed by its source for 4+ days -> filled or closed. Jobs you're already pursuing stay visible.
        base = base.where(or_(Job.last_seen_at >= datetime.now(UTC) - timedelta(days=4), JobMatch.stage.in_(ACTIVE_STAGES)))

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    order = {
        "score": JobMatch.score.desc(),
        "recent": JobMatch.created_at.desc(),
        "posted": Job.posted_at.desc().nulls_last(),
    }[sort]
    rows = (await session.execute(base.order_by(order, JobMatch.id).limit(limit).offset(offset))).all()
    items = [to_out(m, ht, pd, ad, sd) for m, ht, pd, ad, sd in rows]
    # Tracker: how often each application's Proof Link was opened (server-side view log).
    opens = {
        mid: (views, last)
        for mid, views, last in (
            await session.execute(
                select(OutreachDraft.match_id, func.sum(ProofLink.views_count), func.max(ProofLink.last_viewed_at))
                .join(ProofLink, ProofLink.application_id == OutreachDraft.id)
                .where(OutreachDraft.match_id.in_([i.id for i in items]))
                .group_by(OutreachDraft.match_id)
            )
        ).all()
    }
    for i in items:
        if i.id in opens:
            i.proof_views, i.proof_last_viewed_at = int(opens[i.id][0] or 0), opens[i.id][1]
    return MatchPage(items=items, total=total)


@router.get("/{match_id}", response_model=MatchDetail)
async def get_match(match_id: uuid.UUID, user: UserDep, session: SessionDep) -> MatchDetail:
    m = await _get(session, user.id, match_id)
    base = to_out_loaded(m)
    return MatchDetail(
        **base.model_dump(exclude={"job"}),
        job=base.job,
        tailored=TailoredOut.model_validate(m.tailored) if m.tailored else None,
        drafts=[DraftOut.model_validate(d) for d in m.drafts],
    )


def apply_stage(m: JobMatch, stage: str) -> None:
    if m.stage == stage:
        return
    now = datetime.now(UTC)
    m.stage = stage
    m.stage_changed_at = now
    if stage == Stage.applied and m.applied_at is None:
        m.applied_at = now
        m.follow_up_at = now + timedelta(days=settings.follow_up_days)
    if stage in (Stage.interview, Stage.offer, Stage.rejected, Stage.archived):
        m.follow_up_at = None


OUTCOME_STAGE = {"interview": Stage.interview, "offer": Stage.offer, "rejected": Stage.rejected}


def record_outcome(m: JobMatch, outcome: str, reason: str | None = None) -> None:
    """What happened to an application. Interviews, offers and rejections also move the Kanban card."""
    m.outcome = outcome
    m.outcome_at = datetime.now(UTC) if outcome != "none" else None
    if reason is not None:
        m.rejection_reason = reason
    if m.applied_at is None and outcome != "none":
        apply_stage(m, Stage.applied)
    if outcome in OUTCOME_STAGE:
        apply_stage(m, OUTCOME_STAGE[outcome])
    if outcome in ("replied", "interview", "offer", "rejected"):
        m.follow_up_at = None


@router.patch("/{match_id}", response_model=MatchOut)
async def update_match(match_id: uuid.UUID, body: MatchUpdate, user: UserDep, session: SessionDep) -> MatchOut:
    m = await _get(session, user.id, match_id)
    if body.stage is not None:
        apply_stage(m, body.stage)
    if body.notes is not None:
        m.notes = body.notes
    if body.user_rating is not None:
        m.user_rating = body.user_rating
    if body.outcome is not None:
        first_interview = body.outcome == "interview" and m.outcome != "interview"
        record_outcome(m, body.outcome, body.rejection_reason)
        if first_interview and (body.interview_evidence or "").strip():
            from app.services.payments import outcome_interview

            try:
                await outcome_interview(session, user, m.job.company)
            except Exception as exc:  # a payment link failing must never block recording the interview
                from app.logging import log

                log.warning("outcome_plan.link_failed", error=type(exc).__name__)
    elif body.rejection_reason is not None:
        m.rejection_reason = body.rejection_reason
    if body.ppo_status is not None:
        m.ppo_status = body.ppo_status
    await session.commit()
    m = await _get(session, user.id, match_id)
    return to_out_loaded(m)


@router.post("/{match_id}/apply", response_model=MatchOut)
async def apply(match_id: uuid.UUID, user: UserDep, session: SessionDep) -> MatchOut:
    """Records that you applied. The client opens the posting's own application page: company ATSs
    (Greenhouse, Lever, Ashby) don't offer a public submit API, so the final click is yours."""
    m = await _get(session, user.id, match_id)
    apply_stage(m, Stage.applied)
    await session.commit()
    m = await _get(session, user.id, match_id)
    return to_out_loaded(m)


class PrepareIn(BaseModel):
    target: int | None = Field(default=None, ge=0, le=100, description="ATS score the tailored resume must reach before it's sent")
    resume: ResumeData | None = Field(default=None, description="Your resume with the skills and figures you confirmed for this job; saved first")


@router.post("/{match_id}/prepare", response_model=RunOut, status_code=202)
async def prepare(match_id: uuid.UUID, user: UserDep, session: SessionDep, body: PrepareIn | None = None) -> RunOut:
    """Tailor + draft outreach for one job on demand, whatever its score or track. With a target, the resume you
    confirmed (keywords you've used, your real figures) is saved first, and the tailored version is only sent if it
    reaches the target."""
    m = await _get(session, user.id, match_id)
    from app.services.usage import enforce_run_limit

    await enforce_run_limit(session, user)
    if body and (body.target is not None or body.resume is not None):
        p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
        if body.resume is not None:
            p.resume = body.resume.model_dump()
        if body.target is not None:
            p.preferences = {**(p.preferences or {}), "ats_target": body.target}
    run, created = await enqueue_run(session, user.id, trigger="prepare", params={"direct": True, "shortlist_ids": [str(m.id)]})
    if not created:
        raise HTTPException(409, "Agents are busy with another run — try again when it finishes")
    if m.stage == Stage.found:
        apply_stage(m, Stage.shortlisted)
    await session.commit()
    await session.refresh(run)
    return RunOut.model_validate(run)


@router.patch("/{match_id}/tailored/bullets/{source_id}", response_model=TailoredOut)
async def decide_bullet(match_id: uuid.UUID, source_id: str, body: BulletDecision, user: UserDep, session: SessionDep) -> TailoredOut:
    """Accept or decline one of Tailor's rewrites. A declined bullet keeps your original wording on the resume."""
    m = await _get(session, user.id, match_id)
    if m.tailored is None:
        raise HTTPException(404, "This job has no tailored resume yet")
    if not any(b.get("source_id") == source_id for b in m.tailored.bullets):
        raise HTTPException(404, "Bullet not found")
    # A new list, so SQLAlchemy sees the JSONB change.
    m.tailored.bullets = [{**b, "declined": body.declined} if b.get("source_id") == source_id else b for b in m.tailored.bullets]
    await session.commit()
    await session.refresh(m.tailored)
    return TailoredOut.model_validate(m.tailored)


@router.get("/{match_id}/resume")
async def tailored_resume(match_id: uuid.UUID, user: UserDep, session: SessionDep, format: Literal["pdf", "docx"] = "pdf") -> Response:
    """Your uploaded resume, tailored for this job (relevant skills first, Tailor's bullets, confirmed skills)."""
    m = await _get(session, user.id, match_id)
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    doc = resume_doc.build(ResumeData.model_validate(profile.resume or {}), m)
    if format == "pdf":
        content, mime = resume_doc.render_pdf(doc), "application/pdf"
    else:
        content, mime = resume_doc.render_docx(doc), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{resume_doc.filename(doc, format)}"'})


@router.get("/{match_id}/contacts", response_model=ContactsOut)
async def contacts(match_id: uuid.UUID, user: UserDep, session: SessionDep) -> ContactsOut:
    """Real, publicly sourced contacts already found for this job's company, best first."""
    m = await _get(session, user.id, match_id)
    domain = m.job.company_domain
    rows = (await session.execute(select(CompanyContact).where(CompanyContact.domain == domain))).scalars().all() if domain else []
    if not rows and m.job.recruiter_email:
        rows = (await session.execute(select(CompanyContact).where(CompanyContact.email == m.job.recruiter_email.lower()))).scalars().all()
    return ContactsOut(domain=domain, hunter_enabled=bool(settings.hunter_api_key), contacts=[ContactOut.model_validate(c) for c in rank(list(rows), m.job)])


@router.post("/{match_id}/contacts/find", response_model=ContactsOut)
async def find(match_id: uuid.UUID, user: UserDep, session: SessionDep, refresh: bool = False) -> ContactsOut:
    """Look up contacts now: the posting, the company's own site, and Hunter.io when configured."""
    m = await _get(session, user.id, match_id)
    found = await find_contacts(m.job, CallContext(user_id=user.id), force=refresh)
    return ContactsOut(domain=m.job.company_domain, hunter_enabled=bool(settings.hunter_api_key), contacts=[ContactOut.model_validate(c) for c in found])


@router.get("/{match_id}/similar", response_model=list[MatchOut])
async def similar(match_id: uuid.UUID, user: UserDep, session: SessionDep, limit: int = Query(default=5, le=20)) -> list[MatchOut]:
    """Nearest jobs to this one in embedding space (pgvector HNSW), among the user's matches."""
    m = await _get(session, user.id, match_id)
    if m.job.embedding is None:
        return []
    dist = Job.embedding.cosine_distance(m.job.embedding)
    rows = (
        await session.execute(
            select(JobMatch)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.user_id == user.id, JobMatch.id != m.id, Job.embedding.is_not(None))
            .order_by(dist)
            .limit(limit)
        )
    ).scalars().all()
    return [to_out(x) for x in rows]


@router.get("/export/labels")
async def export_labels(user: UserDep, session: SessionDep) -> list[dict]:
    """Your 1-5 ratings as an eval set (see evals/run_evals.py --labels)."""
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    rows = (
        await session.execute(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.user_rating.is_not(None)))
    ).scalars().all()
    return [
        {
            "job_title": m.job.title,
            "company": m.job.company,
            "description": m.job.description,
            "rating": m.user_rating,
            "model_score": m.score,
            "resume_filename": profile.resume_filename,
        }
        for m in rows
    ]


@router.get("/{match_id}/ats-target")
async def ats_target(match_id: uuid.UUID, user: UserDep, session: SessionDep) -> dict:
    """The exact resume that would be sent for this job, scored against it, and your target."""
    from app.services.ats import tailored_score

    m = await _get(session, user.id, match_id)
    p = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    resume = ResumeData.model_validate(p.resume or {})
    target = int((p.preferences or {}).get("ats_target") or 0)
    sc = tailored_score(resume, m) if (resume.experience or resume.projects or resume.skills) else 0
    return {"score": sc, "target": target, "ok": not target or sc >= target, "tailored": m.tailored is not None}

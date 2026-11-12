import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.api.deps import SessionDep, UserDep
from app.api.routes.matches import apply_stage
from app.models import CompanyContact, Consent, DraftStatus, Job, JobMatch, OutreachDraft, Stage, TailoredResume, User
from app.services import quota
from app.schemas import ContactOut, DraftDecision, DraftEdit, DraftWithJob
from app.safety.policy import PolicyDenied
from app.services.applications import BelowTarget, NotSendable, send_application
from app.services.mailer import SendTooSoon, user_sender
from app.services.runs import request_resume

router = APIRouter(prefix="/drafts", tags=["approvals"])

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def _apply_edits(session, d: OutreachDraft, body: DraftEdit) -> None:
    edits = body.model_dump(exclude_none=True, exclude={"decision", "reason"})
    if "contact_id" in edits:
        contact = await session.get(CompanyContact, edits.pop("contact_id"))
        if contact is None:
            raise HTTPException(404, "Contact not found")
        d.contact_id, d.contact, d.to_email = contact.id, contact, contact.email
        edits.pop("to_email", None)
    if "cc_email" in edits:
        cc = edits.pop("cc_email").strip()
        if cc and not _EMAIL.match(cc):
            raise HTTPException(422, "That CC doesn't look like an email address")
        d.cc_email = cc or None
    if "to_email" in edits:
        to = edits.pop("to_email").strip()
        if to and not _EMAIL.match(to):
            raise HTTPException(422, "That doesn't look like an email address")
        d.to_email = to or None
        if d.contact is not None and d.contact.email != d.to_email:
            d.contact_id, d.contact = None, None  # typed a different address: no longer that contact
    for field, value in edits.items():
        setattr(d, field, value)


def _with_job(d: OutreachDraft, m: JobMatch, j: Job, worth: tuple[int, dict[str, int]] | None = None) -> DraftWithJob:
    return DraftWithJob(
        id=d.id,
        match_id=d.match_id,
        kind=d.kind,
        run_id=d.run_id,
        subject=d.subject,
        email_body=d.email_body,
        linkedin_note=d.linkedin_note,
        to_email=d.to_email,
        contact_id=d.contact_id,
        contact=ContactOut.model_validate(d.contact) if d.contact else None,
        cc_email=d.cc_email,
        status=d.status,
        decided_at=d.decided_at,
        sent_at=d.sent_at,
        created_at=d.created_at,
        company=j.company,
        title=j.title,
        score=m.score,
        job_url=j.url,
        job_source=j.source,
        recruiter_email=j.recruiter_email,
        legit_status=j.legit_status,
        legit_reasons=j.legit_reasons or [],
        ghost_score=j.ghost_score,
        send_worthiness=d.send_worthiness if d.send_worthiness is not None else (worth[0] if worth else None),
        worthiness_parts=worth[1] if worth else {},
        injection_signals=j.injection_signals or [],
        **_recipient(d, j),
        void_reason=d.void_reason,
        reject_reason=d.reject_reason,
    )


def _recipient(d: OutreachDraft, j: Job) -> dict:
    from app.safety.recipients import recipient_ok

    to = d.to_email or j.recruiter_email
    if not to:
        return {"recipient_basis": None, "recipient_note": ""}
    v = recipient_ok(to, job_recruiter_email=j.recruiter_email, job_url=j.url, company_domain=j.company_domain, contact=d.contact)
    note = {
        "posting": "Printed on the posting itself",
        "company_page": "Listed on the company's own website",
        "hunter": "A verified address with cited public sources",
        "entered_by_you": "An address you typed in yourself",
    }.get(v.basis, v.reason)
    return {"recipient_basis": v.basis, "recipient_note": note}


def _block_scams(j: Job) -> None:
    """Verifier v2: a posting judged "Likely scam" can never be approved or sent, whatever the UI shows."""
    if j.legit_status == "suspicious":
        raise HTTPException(409, "This posting was flagged as a likely scam, so it can't be approved: " + "; ".join(j.legit_reasons[:2]))


async def _load(session, user_id: uuid.UUID, draft_id: uuid.UUID):
    row = (
        await session.execute(
            select(OutreachDraft, JobMatch, Job)
            .join(JobMatch, JobMatch.id == OutreachDraft.match_id)
            .join(Job, Job.id == JobMatch.job_id)
            .where(OutreachDraft.id == draft_id, OutreachDraft.user_id == user_id)
            .with_for_update(of=OutreachDraft)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Draft not found")
    return row


@router.get("", response_model=list[DraftWithJob])
async def list_drafts(user: UserDep, session: SessionDep, status: str | None = "pending") -> list[DraftWithJob]:
    q = (
        select(OutreachDraft, JobMatch, Job)
        .join(JobMatch, JobMatch.id == OutreachDraft.match_id)
        .join(Job, Job.id == JobMatch.job_id)
        .where(OutreachDraft.user_id == user.id)
    )
    if status:
        q = q.where(OutreachDraft.status == status)
    rows = (await session.execute(q.order_by(JobMatch.score.desc(), OutreachDraft.created_at.desc()).limit(200))).all()
    tailored = {
        t.match_id: t for t in (await session.execute(select(TailoredResume).where(TailoredResume.match_id.in_([m.id for _, m, _ in rows])))).scalars()
    }
    proof = (await session.execute(select(Consent.id).where(Consent.user_id == user.id, Consent.purpose == "public_proof", Consent.withdrawn_at.is_(None)))).first() is not None
    return [_with_job(d, m, j, quota.send_worthiness(m, j, d, tailored.get(m.id), proof)) for d, m, j in rows]


async def approve(session, user: User, d: OutreachDraft, m: JobMatch, j: Job, channel: str = "web", request: Request | None = None) -> None:
    """The one way a draft becomes approved (web or WhatsApp): scam block, daily quota, send-worthiness and the
    audit event, then the run resumes once its last draft is decided."""
    _block_scams(j)
    await quota.consume(session, user)
    d.send_worthiness = (await quota.draft_worthiness(session, d, m, j))[0]
    d.status, d.decided_at, d.approval_channel = DraftStatus.approved, datetime.now(UTC), channel
    apply_stage(m, Stage.applied)
    await quota.record(session, d.id, user.id, "approve", channel, request)
    await session.flush()
    from app.services.proof_links import create_for

    await create_for(session, user, d, m, j)  # the signed Proof Link for this application (if the proof page is published)
    # Bind the approval to this exact email (recipient, subject, body, attachment, mailbox): see app/safety/mandates.py.
    from app.models import Profile
    from app.safety import mandates
    from app.services.applications import build_payload

    from sqlalchemy.orm import selectinload

    await session.flush()
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    m = (await session.execute(select(JobMatch).where(JobMatch.id == m.id).options(selectinload(JobMatch.tailored), selectinload(JobMatch.job)))).scalar_one()
    payload, _ = await build_payload(session, d, m, profile)
    await mandates.issue(session, user.id, d.id, payload, channel)
    await _maybe_resume(session, d)


async def _maybe_resume(session, d: OutreachDraft) -> None:
    # When the last draft of a run is decided, hand the run back to the worker to resume the graph.
    if d.run_id:
        await session.flush()
        remaining = (
            await session.execute(select(func.count()).where(OutreachDraft.run_id == d.run_id, OutreachDraft.status == DraftStatus.pending))
        ).scalar_one()
        if remaining == 0:
            await request_resume(session, d.run_id)


@router.patch("/{draft_id}", response_model=DraftWithJob)
async def edit_draft(draft_id: uuid.UUID, body: DraftEdit, user: UserDep, session: SessionDep) -> DraftWithJob:
    d, m, j = await _load(session, user.id, draft_id)
    if d.status not in (DraftStatus.pending, DraftStatus.approved):
        raise HTTPException(409, "Sent or rejected drafts can't be edited")
    await _apply_edits(session, d, body)
    if d.status == DraftStatus.approved:
        # An approval covers the email as it was: an edited one goes back to the queue for a fresh approval.
        from app.safety import mandates

        await mandates.void(session, d.id, "edited")
        d.status, d.decided_at = DraftStatus.pending, None
        await quota.refund(session, user.id)
    await session.commit()
    return _with_job(d, m, j)


@router.post("/{draft_id}/decision", response_model=DraftWithJob)
async def decide(draft_id: uuid.UUID, body: DraftDecision, user: UserDep, session: SessionDep, request: Request) -> DraftWithJob:
    d, m, j = await _load(session, user.id, draft_id)
    if d.status != DraftStatus.pending:
        raise HTTPException(409, f"Draft already {d.status}")
    await _apply_edits(session, d, body)
    if body.decision == "approve":
        await approve(session, user, d, m, j, "web", request)
    else:
        reason = (body.reason or "").strip()
        if len(reason) < 3:
            raise HTTPException(422, "Say briefly why you're rejecting it (it helps us improve the drafts)")
        d.status, d.decided_at, d.reject_reason = DraftStatus.rejected, datetime.now(UTC), reason[:300]
        await quota.record(session, d.id, user.id, "reject", "web", request)
        await _maybe_resume(session, d)
    await session.commit()
    return _with_job(d, m, j, await quota.draft_worthiness(session, d, m, j))


@router.post("/{draft_id}/mark-sent", response_model=DraftWithJob)
async def mark_sent(draft_id: uuid.UUID, user: UserDep, session: SessionDep) -> DraftWithJob:
    """For drafts the user sent themselves (copy / mailto / LinkedIn)."""
    d, m, j = await _load(session, user.id, draft_id)
    if d.status not in (DraftStatus.approved, DraftStatus.sent):
        raise HTTPException(409, "Approve the draft first")
    d.status = DraftStatus.sent
    d.sent_at = d.sent_at or datetime.now(UTC)
    await session.commit()
    return _with_job(d, m, j)


@router.post("/{draft_id}/send", response_model=DraftWithJob)
async def send(draft_id: uuid.UUID, body: DraftEdit, user: UserDep, session: SessionDep, request: Request) -> DraftWithJob:
    """One click: approve (if still pending) and email the application with the tailored resume
    attached, from your own mailbox (connected in Settings)."""
    if await user_sender(user.id) is None:
        raise HTTPException(409, "Connect your email in Settings to send from your own address, or use Open in Gmail")
    d, m, j = await _load(session, user.id, draft_id)
    if d.status in (DraftStatus.rejected, DraftStatus.sent):
        raise HTTPException(409, f"Draft already {d.status}")
    _block_scams(j)
    await _apply_edits(session, d, body)
    if not d.to_email:
        raise HTTPException(422, "Add the recipient's email address first")
    if d.status == DraftStatus.pending:
        await approve(session, user, d, m, j, "web", request)
    await session.commit()
    try:
        await send_application(d.id)
    except NotSendable as exc:
        raise HTTPException(409, str(exc)) from exc
    except PolicyDenied as exc:
        raise HTTPException(423, str(exc)) from exc
    except SendTooSoon as exc:
        raise HTTPException(429, f"Approved. {exc}", headers={"retry-after": str(exc.wait_s)}) from exc
    except BelowTarget as exc:
        raise HTTPException(409, f"Approved, not sent: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Approved, but the email couldn't be sent: {exc}") from exc
    await session.refresh(d)  # the send was recorded in its own transaction
    return _with_job(d, m, j)

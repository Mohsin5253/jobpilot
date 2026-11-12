"""Sending an approved application email, with the tailored resume attached."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.models import ApprovalEvent, DraftStatus, JobMatch, OutreachDraft, Profile, ProofLink
from app.schemas import ResumeData
from app.services import proof_links, resume_doc
from app.safety.mandates import SendPayload, doc_sha256, resume_version
from app.services.mailer import send_as_user


# Outreach etiquette: every application email says how to opt out of the one follow-up.
OPT_OUT = "If this isn't relevant, just reply \"no\" and I won't follow up."


class BelowTarget(Exception):
    """The tailored resume scores below the student's ATS target for this job: it isn't sent."""

    def __init__(self, score: int, target: int):
        super().__init__(f"Your tailored resume scores {score} for this job, below your target of {target}. Open the job and use “Reach target” first.")
        self.score, self.target = score, target


def check_target(resume: ResumeData, match, prefs: dict) -> tuple[int, int]:
    """(score, target) for the resume that would be sent; raises BelowTarget when a target is set and not met."""
    from app.services.ats import tailored_score

    target = int((prefs or {}).get("ats_target") or 0)
    sc = tailored_score(resume, match)
    if target and sc < target:
        raise BelowTarget(sc, target)
    return sc, target


def with_opt_out(body: str) -> str:
    return body if "won't follow up" in body else f"{body.rstrip()}\n\n{OPT_OUT}"


async def build_payload(s, draft: OutreachDraft, match: JobMatch, profile: Profile) -> tuple[SendPayload, object]:
    """The exact email that would go out for this draft, and the resume document behind its attachment. Used both
    when it's approved (to bind the approval to it) and right before it's sent (to check nothing changed)."""
    from app.models import MailAccount

    link = (await s.execute(select(ProofLink).where(ProofLink.application_id == draft.id, ProofLink.revoked_at.is_(None)))).scalar_one_or_none()
    body = draft.email_body
    if link:
        signed = proof_links.url_for(link)
        generic = f"/p/{link.slug}"
        body = re.sub(re.escape(generic) + r"(?![/\w-])", f"/p/{link.slug}/{link.token}", body) if generic in body else f"{body.rstrip()}\n\nProof of my work (verified): {signed}"
    resume = ResumeData.model_validate(profile.resume or {})
    doc = resume_doc.build(resume, match)
    acct = await s.get(MailAccount, draft.user_id)
    payload = SendPayload(
        to=(draft.to_email or match.job.recruiter_email or "").strip().lower(),
        cc=(draft.cc_email or "").strip().lower(),
        subject=draft.subject,
        body=with_opt_out(body),
        attachment_name=resume_doc.filename(doc, "pdf"),
        attachment_sha256=doc_sha256(doc),
        job_id=str(match.job_id),
        from_mailbox=(acct.from_email if acct else "").lower(),
        resume_version_id=resume_version(profile.resume),
    )
    return payload, doc


class NotSendable(PermissionError):
    pass


async def send_application(draft_id: uuid.UUID, wait: bool = False, channel: str = "web") -> OutreachDraft:
    """Dispatch: the only code that sends an application. Emails an approved draft from the user's own mailbox with
    the job-tailored resume attached, and only when every precondition holds in code:
    approved status · a payload-bound, unused, unexpired approval grant whose hash matches what is about to be sent ·
    the kill switch off · the posting not blocked · the recipient allowed by the contact policy · the resume at the
    student's ATS target · the 'sending' consent active and >= 90 s since the last send (checked in the mailer)."""
    from app.models import CompanyContact
    from app.safety import mandates, policy
    from app.safety.recipients import recipient_ok

    async with session_scope() as s:
        draft = (await s.execute(select(OutreachDraft).where(OutreachDraft.id == draft_id).with_for_update(of=OutreachDraft))).scalar_one()
        match = (
            await s.execute(select(JobMatch).where(JobMatch.id == draft.match_id).options(selectinload(JobMatch.tailored), selectinload(JobMatch.job)))
        ).scalar_one()
        profile = (await s.execute(select(Profile).where(Profile.user_id == draft.user_id))).scalar_one()
        if draft.status != DraftStatus.approved:
            raise NotSendable(f"Only an approved draft can be sent (this one is {draft.status})")
        if match.job.legit_status == "suspicious":  # defence in depth: the routes and a database trigger refuse these too
            raise PermissionError("This posting was flagged as a likely scam and can't be sent")
        resume = ResumeData.model_validate(profile.resume or {})
        check_target(resume, match, profile.preferences or {})  # only a resume that reached the target is sent
        payload, doc = await build_payload(s, draft, match, profile)
        contact = await s.get(CompanyContact, draft.contact_id) if draft.contact_id else None
        rv = recipient_ok(payload.to, job_recruiter_email=match.job.recruiter_email, job_url=match.job.url, company_domain=match.job.company_domain, contact=contact)
        if not rv.allowed:
            raise NotSendable(f"Not sent: the recipient isn't allowed ({rv.reason}). Choose another contact or type the address yourself.")
        if payload.cc:
            cc_contact = (await s.execute(select(CompanyContact).where(CompanyContact.email == payload.cc).limit(1))).scalar_one_or_none()
            cv = recipient_ok(payload.cc, job_recruiter_email=match.job.recruiter_email, job_url=match.job.url, company_domain=match.job.company_domain, contact=cc_contact)
            if not cv.allowed:
                raise NotSendable(f"Not sent: the CC isn't allowed ({cv.reason}).")
        try:
            grant_id = await mandates.claim(s, draft.user_id, draft.id, payload)
        except mandates.MandateInvalid as exc:
            # The approval no longer covers this email: back to the queue for a fresh look.
            draft.status, draft.decided_at = DraftStatus.pending, None
            from app.services import quota

            await quota.refund(s, draft.user_id)
            await s.commit()  # keep the voided grant and the draft's return to the queue
            raise NotSendable(str(exc)) from exc
        await policy.authorize("dispatch", "email.send", {"draft_id": str(draft.id)}, policy.Context(user_id=draft.user_id, grant_ok=True))
    try:
        await send_as_user(
            draft.user_id,
            payload.to,
            payload.subject,
            payload.body,
            wait=wait,
            reply_to=resume.email or None,
            attachments=[(payload.attachment_name, resume_doc.render_pdf(doc), "application/pdf")],
            cc=payload.cc or None,
        )
    except Exception:
        await mandates.release(grant_id)  # nothing left: the same approval may be retried once more
        raise
    async with session_scope() as s:
        row = await s.get(OutreachDraft, draft_id)
        row.status = DraftStatus.sent
        row.sent_at = datetime.now(UTC)
        s.add(ApprovalEvent(application_id=row.id, user_id=row.user_id, action="send", channel=row.approval_channel or channel))  # audit: every send
        return row

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


async def send_application(draft_id: uuid.UUID, wait: bool = False, channel: str = "web") -> OutreachDraft:
    """Email an approved draft from the user's own mailbox, with the job-tailored resume PDF attached; marks it
    sent. Raises MailNotConnected if they haven't connected one."""
    async with session_scope() as s:
        draft = await s.get(OutreachDraft, draft_id)
        match = (
            await s.execute(select(JobMatch).where(JobMatch.id == draft.match_id).options(selectinload(JobMatch.tailored)))
        ).scalar_one()
        profile = (await s.execute(select(Profile).where(Profile.user_id == draft.user_id))).scalar_one()
    async with session_scope() as s:
        link = (await s.execute(select(ProofLink).where(ProofLink.application_id == draft_id, ProofLink.revoked_at.is_(None)))).scalar_one_or_none()
    body = draft.email_body
    if link:
        signed = proof_links.url_for(link)
        generic = f"/p/{link.slug}"
        body = re.sub(re.escape(generic) + r"(?![/\w-])", f"/p/{link.slug}/{link.token}", body) if generic in body else f"{body.rstrip()}\n\nProof of my work (verified): {signed}"
    if match.job.legit_status == "suspicious":  # defence in depth: the routes refuse these first
        raise PermissionError("This posting was flagged as a likely scam and can't be sent")
    resume = ResumeData.model_validate(profile.resume or {})
    check_target(resume, match, profile.preferences or {})  # only a resume that reached the target is sent
    doc = resume_doc.build(resume, match)
    await send_as_user(
        draft.user_id,
        draft.to_email or match.job.recruiter_email or "",
        draft.subject,
        with_opt_out(body),
        wait=wait,
        reply_to=resume.email or None,
        attachments=[(resume_doc.filename(doc, "pdf"), resume_doc.render_pdf(doc), "application/pdf")],
        cc=draft.cc_email,
    )
    async with session_scope() as s:
        row = await s.get(OutreachDraft, draft_id)
        row.status = DraftStatus.sent
        row.sent_at = datetime.now(UTC)
        s.add(ApprovalEvent(application_id=row.id, user_id=row.user_id, action="send", channel=row.approval_channel or channel))  # audit: every send
        return row

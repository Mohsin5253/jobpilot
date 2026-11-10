"""Sending an approved application email, with the tailored resume attached."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.models import DraftStatus, JobMatch, OutreachDraft, Profile
from app.schemas import ResumeData
from app.services import resume_doc
from app.services.mailer import send_as_user


async def send_application(draft_id: uuid.UUID) -> OutreachDraft:
    """Email an approved draft from the user's own mailbox, with the job-tailored resume PDF attached; marks it
    sent. Raises MailNotConnected if they haven't connected one."""
    async with session_scope() as s:
        draft = await s.get(OutreachDraft, draft_id)
        match = (
            await s.execute(select(JobMatch).where(JobMatch.id == draft.match_id).options(selectinload(JobMatch.tailored)))
        ).scalar_one()
        profile = (await s.execute(select(Profile).where(Profile.user_id == draft.user_id))).scalar_one()
    resume = ResumeData.model_validate(profile.resume or {})
    doc = resume_doc.build(resume, match)
    await send_as_user(
        draft.user_id,
        draft.to_email or match.job.recruiter_email or "",
        draft.subject,
        draft.email_body,
        reply_to=resume.email or None,
        attachments=[(resume_doc.filename(doc, "pdf"), resume_doc.render_pdf(doc), "application/pdf")],
        cc=draft.cc_email,
    )
    async with session_scope() as s:
        row = await s.get(OutreachDraft, draft_id)
        row.status = DraftStatus.sent
        row.sent_at = datetime.now(UTC)
        return row

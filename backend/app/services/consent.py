"""Consent (India's DPDP Act): what each user agreed to, when, and to which version of the notice.

`core` (processing your resume to find and prepare applications) is given at sign-up and only ends with the
account. The others are opt-in and can be withdrawn any time; withdrawing switches the feature off at once.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Consent

PURPOSES = {
    "core": "Process my resume and preferences to find, score and prepare applications",
    "sending": "Send the applications I approve from my own mailbox",
    "public_proof": "Publish my proof-of-skills page at a link I can share",
    "whatsapp": "Send me a daily WhatsApp digest of my best new matches",
    "college_share": "Share what I create in JobPilot (applications, matches, internships, roles, awards and proof) with my college's placement staff, by name",
    "ledger": "Add my stipend and PPO reports to the anonymous company ledger",
}

# The itemized notice (DPDP Act s.5): for each purpose, the personal data used, why, how long it's kept and how to
# withdraw. Shown at sign-up and in Settings; bump settings.consent_version whenever this text changes.
NOTICE: dict[str, dict[str, str]] = {
    "core": {
        "data": "Your name, email, resume, the skills you confirm and your search preferences.",
        "why": "To find internships that fit you, score them, tailor your resume and draft applications.",
        "retention": "While your account is open. Accounts unused for 12 months are deleted after a notice.",
        "withdraw": "Delete your account in Settings → Your data. Everything is deleted at once.",
    },
    "sending": {
        "data": "Your mailbox connection (a Google token limited to sending, or an app password), stored encrypted.",
        "why": "To send each application you approve from your own address. Nothing is sent without your approval.",
        "retention": "Until you disconnect your mailbox or delete your account.",
        "withdraw": "Disconnect your mailbox in Settings → Your email, or switch this off in Settings → Privacy.",
    },
    "public_proof": {
        "data": "Your name, education, verified GitHub and Codeforces data, projects and certificates. Never your email, phone or resume.",
        "why": "To publish a proof page recruiters can check.",
        "retention": "Published until you unpublish it.",
        "withdraw": "Unpublish it in Proof, or switch this off in Settings → Privacy. The page goes offline at once.",
    },
    "whatsapp": {
        "data": "Your WhatsApp number and a short summary of your best new matches.",
        "why": "To send you a daily digest through the official WhatsApp Cloud API.",
        "retention": "Until you stop the digest.",
        "withdraw": "Reply STOP on WhatsApp, or switch this off in Settings.",
    },
    "college_share": {
        "data": "Your applications, matches, drive registrations and outcomes, and the internships, roles and awards you add with their proof. (Your college's own records about you, such as roll number, programme and score, are the college's and visible to the staff responsible for you either way.)",
        "why": "So your college's placement staff can support you and verify your entries. Without this they see only anonymous totals of what you create in JobPilot.",
        "retention": "Until you withdraw or leave the college workspace. Withdrawal removes you from their views within 24 hours.",
        "withdraw": "Switch this off in Campus or Settings → Privacy.",
    },
    "ledger": {
        "data": "Stipend, duration, work mode, PPO and paid-on-time answers for a company you interned at.",
        "why": "To show students anonymous stipend ranges. A company's numbers appear only once 3 or more students report.",
        "retention": "Kept anonymously; verification documents are deleted right after checking.",
        "withdraw": "Switch this off in Settings → Privacy. Your reports are removed from the ledger.",
    },
}


async def active(s: AsyncSession, user_id: uuid.UUID) -> dict[str, Consent]:
    rows = (await s.execute(select(Consent).where(Consent.user_id == user_id, Consent.withdrawn_at.is_(None)))).scalars().all()
    return {c.purpose: c for c in rows}


async def has(s: AsyncSession, user_id: uuid.UUID, purpose: str) -> bool:
    return purpose in await active(s, user_id)


async def grant(s: AsyncSession, user_id: uuid.UUID, purpose: str, method: str = "checkbox", guardian_user_id: uuid.UUID | None = None) -> None:
    if purpose not in PURPOSES:
        raise ValueError(purpose)
    if not await has(s, user_id, purpose):
        s.add(Consent(user_id=user_id, purpose=purpose, notice_version=settings.consent_version, method=method, guardian_user_id=guardian_user_id))


async def withdraw(s: AsyncSession, user_id: uuid.UUID, purpose: str) -> None:
    await s.execute(
        update(Consent).where(Consent.user_id == user_id, Consent.purpose == purpose, Consent.withdrawn_at.is_(None)).values(withdrawn_at=datetime.now(UTC))
    )

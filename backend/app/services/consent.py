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
    "public_proof": "Publish my proof-of-skills page at a link I can share",
    "whatsapp": "Send me a daily WhatsApp digest of my best new matches",
    "college_share": "Share my placement progress with my college's placement cell",
}


async def active(s: AsyncSession, user_id: uuid.UUID) -> dict[str, Consent]:
    rows = (await s.execute(select(Consent).where(Consent.user_id == user_id, Consent.withdrawn_at.is_(None)))).scalars().all()
    return {c.purpose: c for c in rows}


async def has(s: AsyncSession, user_id: uuid.UUID, purpose: str) -> bool:
    return purpose in await active(s, user_id)


async def grant(s: AsyncSession, user_id: uuid.UUID, purpose: str) -> None:
    if purpose not in PURPOSES:
        raise ValueError(purpose)
    if not await has(s, user_id, purpose):
        s.add(Consent(user_id=user_id, purpose=purpose, version=settings.consent_version))


async def withdraw(s: AsyncSession, user_id: uuid.UUID, purpose: str) -> None:
    await s.execute(
        update(Consent).where(Consent.user_id == user_id, Consent.purpose == purpose, Consent.withdrawn_at.is_(None)).values(withdrawn_at=datetime.now(UTC))
    )

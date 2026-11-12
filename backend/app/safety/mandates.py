"""Approval mandates: an approval covers one exact email, once.

When a student approves a draft, the server builds the canonical payload that would actually be sent
{to, cc, subject, body, attachment_sha256, job_id, from_mailbox, resume_version_id} and stores
ApprovalGrant{payload_hash, expires_at, used_at}. Nothing from the client or a model is trusted for this.

Dispatch rebuilds the payload right before sending and goes ahead only if the hash matches and the grant is this
user's, unexpired, unused and not voided. The grant is marked used in the same transaction that claims the send
(its id is the idempotency key), so a replay, a double click or a second worker can't send twice. Editing the draft,
changing the resume behind the attachment, or the posting being blocked voids the grant: it needs a fresh approval.
"""

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging import log


class MandateInvalid(PermissionError):
    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.code = code


@dataclass
class SendPayload:
    to: str
    cc: str
    subject: str
    body: str
    attachment_name: str
    attachment_sha256: str
    job_id: str
    from_mailbox: str
    resume_version_id: str

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


def doc_sha256(doc) -> str:
    """The attachment's content (the tailored resume document the PDF is rendered from). Hashing the model, not the PDF
    bytes, because PDF files embed a creation time."""
    return hashlib.sha256(json.dumps(asdict(doc), sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def resume_version(resume_json: dict | None) -> str:
    return hashlib.sha256(json.dumps(resume_json or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def issue(s: AsyncSession, user_id: uuid.UUID, draft_id: uuid.UUID, payload: SendPayload, channel: str) -> uuid.UUID:
    """A fresh grant for this exact payload; any earlier unused grant for the draft is voided."""
    from app.models import ApprovalGrant

    now = datetime.now(UTC)
    await s.execute(
        update(ApprovalGrant)
        .where(ApprovalGrant.draft_id == draft_id, ApprovalGrant.used_at.is_(None), ApprovalGrant.voided_at.is_(None))
        .values(voided_at=now, void_reason="superseded")
    )
    g = ApprovalGrant(user_id=user_id, draft_id=draft_id, payload_hash=payload.hash, channel=channel, expires_at=now + timedelta(minutes=settings.approval_grant_ttl_min))
    s.add(g)
    await s.flush()
    log.info("approval.granted", draft_id=str(draft_id), grant_id=str(g.id), channel=channel)
    return g.id


async def void(s: AsyncSession, draft_id: uuid.UUID, reason: str) -> int:
    from app.models import ApprovalGrant

    res = await s.execute(
        update(ApprovalGrant)
        .where(ApprovalGrant.draft_id == draft_id, ApprovalGrant.used_at.is_(None), ApprovalGrant.voided_at.is_(None))
        .values(voided_at=datetime.now(UTC), void_reason=reason[:40])
    )
    return res.rowcount or 0


async def claim(s: AsyncSession, user_id: uuid.UUID, draft_id: uuid.UUID, payload: SendPayload) -> uuid.UUID:
    """Check and use the grant for this send (row-locked). Raises MandateInvalid with the reason otherwise."""
    from app.models import ApprovalGrant

    g = (
        await s.execute(
            select(ApprovalGrant)
            .where(ApprovalGrant.draft_id == draft_id, ApprovalGrant.voided_at.is_(None))
            .order_by(ApprovalGrant.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if g is None:
        raise MandateInvalid("This email has no approval. Approve it first.", "no_grant")
    if g.user_id != user_id:
        raise MandateInvalid("This approval belongs to someone else.", "wrong_user")
    if g.used_at is not None:
        raise MandateInvalid("This approval was already used. Each approval sends one email once.", "used")
    if g.expires_at <= datetime.now(UTC):
        g.voided_at, g.void_reason = datetime.now(UTC), "expired"
        raise MandateInvalid(f"Approvals expire after {settings.approval_grant_ttl_min} minutes without sending. Approve it again.", "expired")
    if g.payload_hash != payload.hash:
        g.voided_at, g.void_reason = datetime.now(UTC), "payload_changed"
        raise MandateInvalid("The email, recipient or attached resume changed after you approved it. Review it and approve again.", "payload_changed")
    g.used_at = datetime.now(UTC)
    return g.id


async def release(grant_id: uuid.UUID) -> None:
    """The send failed before anything left (network, provider): the grant may be used for one more attempt."""
    from app.db import session_scope
    from app.models import ApprovalGrant

    async with session_scope() as s:
        await s.execute(update(ApprovalGrant).where(ApprovalGrant.id == grant_id).values(used_at=None))

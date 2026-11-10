"""Signed Proof Links (F4).

Each approved application (when the student has published their proof page) gets /p/{slug}/{token}. The token is
`{id}.{tag}`: a random id plus the first 9 bytes of an Ed25519 signature over "{slug}/{id}", so changing any
character fails. The page's payload (who, which role, when the student approved it, what's verified) is signed in
full with the same key; /api/v1/verify/{token} returns it with the signature and the public key, so a recruiter can
check it independently.

The signing key is PROOF_SIGNING_KEY (32-byte seed, base64) when set, otherwise derived from ENCRYPTION_KEY, which
production already requires, so there's no new mandatory variable. Views are logged server-side as a browser family
only (no IP, no cookies, no third-party pixels); link-preview bots are logged but not counted.
"""

import base64
import hashlib
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Job, JobMatch, Notification, OutreachDraft, Profile, ProofLink, ProofLinkView, TailoredResume, User
from app.schemas import ResumeData
from app.services.consent import has


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@lru_cache
def _key() -> Ed25519PrivateKey:
    if settings.proof_signing_key:
        seed = _unb64(settings.proof_signing_key.strip())
    else:
        seed = hashlib.sha256(f"jobpilot-proof-sign:{settings.encryption_key or settings.jwt_secret}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def public_key_b64() -> str:
    raw = _key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(raw)


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(payload: dict) -> str:
    return _b64(_key().sign(canonical(payload)))


def verify_signature(payload: dict, signature: str, public_key: str | None = None) -> bool:
    pub = Ed25519PublicKey.from_public_bytes(_unb64(public_key or public_key_b64()))
    try:
        pub.verify(_unb64(signature), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def make_token(slug: str, link_id: str) -> str:
    return f"{link_id}.{_b64(_key().sign(f'{slug}/{link_id}'.encode())[:9])}"


def token_ok(slug: str, token: str) -> bool:
    link_id, _, tag = token.partition(".")
    return bool(link_id and tag) and secrets.compare_digest(make_token(slug, link_id), token)


def url_for(link: ProofLink) -> str:
    return f"{settings.app_url.rstrip('/')}/p/{link.slug}/{link.token}"


async def create_for(s: AsyncSession, user: User, draft: OutreachDraft, match: JobMatch, job: Job) -> ProofLink | None:
    """Issued when an application is approved, only if the student has published their proof page."""
    existing = (await s.execute(select(ProofLink).where(ProofLink.application_id == draft.id))).scalar_one_or_none()
    if existing:
        return existing
    profile = (await s.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None or not profile.proof_slug or not await has(s, user.id, "public_proof"):
        return None
    now = datetime.now(UTC)
    week_start = now - timedelta(days=now.weekday(), hours=now.hour, minutes=now.minute, seconds=now.second)
    sent_week = (
        await s.execute(
            select(func.count()).where(OutreachDraft.user_id == user.id, OutreachDraft.status.in_(["approved", "sent"]), OutreachDraft.decided_at >= week_start)
        )
    ).scalar_one()
    tailored = (await s.execute(select(TailoredResume).where(TailoredResume.match_id == match.id))).scalar_one_or_none()
    ev = profile.evidence or {}
    gh = ev.get("github") or {}
    resume = ResumeData.model_validate(profile.resume or {})
    link_id = secrets.token_urlsafe(8)
    payload = {
        "v": 1,
        "link": link_id,
        "slug": profile.proof_slug,
        "student": resume.name or user.name or "JobPilot candidate",
        "role": job.title,
        "company": job.company,
        "approved_at": (draft.decided_at or now).isoformat(timespec="seconds"),
        "approved_by": "student",
        "applications_this_week": max(1, int(sent_week)),
        # After the guard every kept bullet cites a source and the rest went back to the original wording.
        "claims_source_verified": bool(tailored and tailored.bullets),
        "github_verified": bool(gh.get("verified")),
        "github_username": gh.get("username") if gh.get("verified") else None,
        "codeforces_rating": (ev.get("codeforces") or {}).get("rating"),
        "issued_at": now.isoformat(timespec="seconds"),
    }
    link = ProofLink(
        id=uuid.uuid4(), user_id=user.id, application_id=draft.id, slug=profile.proof_slug, token=make_token(profile.proof_slug, link_id),
        payload=payload, signature=sign(payload),
    )
    s.add(link)
    return link


_BOTS = re.compile(r"bot|crawler|spider|preview|facebookexternalhit|whatsapp|slack|telegram|discord|googleimageproxy|curl|python|wget|headless", re.I)


def ua_family(ua: str) -> str:
    ua = ua or ""
    if _BOTS.search(ua):
        return "bot"
    for fam, pat in (("edge", r"Edg/"), ("opera", r"OPR/"), ("samsung", r"SamsungBrowser"), ("chrome", r"Chrome/"), ("firefox", r"Firefox/"), ("safari", r"Safari/")):
        if re.search(pat, ua):
            return fam + ("-mobile" if re.search(r"Mobile|Android|iPhone", ua) else "")
    return "other"


async def record_view(s: AsyncSession, link: ProofLink, ua: str) -> None:
    fam = ua_family(ua)
    s.add(ProofLinkView(proof_link_id=link.id, ua_family=fam))
    if fam == "bot":
        return
    first = link.views_count == 0
    link.views_count += 1
    link.last_viewed_at = datetime.now(UTC)
    if first:
        draft = await s.get(OutreachDraft, link.application_id)
        s.add(
            Notification(
                user_id=link.user_id, kind="proof_view", match_id=draft.match_id if draft else None,
                title=f"Your proof link for {link.payload.get('company', 'an application')} was opened",
                body="Someone opened the proof page in your application. Follow up if you haven't heard back in a week.",
            )
        )

"""Signed Proof Links: the student's list (with opens) and revoke, the public page data, and recruiter verification."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.models import ProofLink, ProofLinkView
from app.schemas import ResumeData
from app.services import proof_links as pl
from app.services.consent import has
from app.services.evidence import public_view

router = APIRouter(tags=["proof-links"])


def _mine(link: ProofLink) -> dict:
    return {
        "id": str(link.id), "url": pl.url_for(link), "company": link.payload.get("company"), "role": link.payload.get("role"),
        "approved_at": link.payload.get("approved_at"), "views": link.views_count,
        "last_viewed_at": link.last_viewed_at.isoformat() if link.last_viewed_at else None,
        "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
    }


@router.get("/proof-links")
async def my_links(user: UserDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(ProofLink).where(ProofLink.user_id == user.id).order_by(ProofLink.created_at.desc()))).scalars().all()
    return [_mine(r) for r in rows]


@router.post("/proof-links/{link_id}/revoke")
async def revoke(link_id: str, user: UserDep, session: SessionDep) -> dict:
    link = await session.get(ProofLink, link_id)
    if link is None or link.user_id != user.id:
        raise HTTPException(404, "No such link")
    link.revoked_at = link.revoked_at or datetime.now(UTC)
    await session.commit()
    return _mine(link)


async def _load(session, slug: str, token: str) -> ProofLink:
    if not pl.token_ok(slug, token):
        raise HTTPException(404, "This proof link isn't valid")
    link = (await session.execute(select(ProofLink).where(ProofLink.token == token, ProofLink.slug == slug))).scalar_one_or_none()
    if link is None or link.revoked_at is not None:
        raise HTTPException(404, "This proof link has been withdrawn")
    return link


@router.get("/public/proof-link/{slug}/{token}")
async def public_link(slug: str, token: str, request: Request, session: SessionDep) -> dict:
    """The page data for /p/{slug}/{token}. Each request is one server-side view (the page isn't cached)."""
    link = await _load(session, slug, token)
    from app.models import Profile

    profile = (await session.execute(select(Profile).where(Profile.user_id == link.user_id))).scalar_one_or_none()
    if profile is None or not await has(session, link.user_id, "public_proof"):
        raise HTTPException(404, "This proof page isn't published")
    resume = ResumeData.model_validate(profile.resume or {})
    edu = resume.education[0] if resume.education else None
    headline = " · ".join(x for x in [(edu.degree if edu else ""), (edu.school if edu else "")] if x)
    await pl.record_view(session, link, request.headers.get("x-viewer-ua") or request.headers.get("user-agent", ""))
    await session.commit()
    return {
        "proof": public_view(profile.evidence or {}, resume.name or "JobPilot candidate", headline),
        "application": link.payload,
        "signature": link.signature,
        "public_key": pl.public_key_b64(),
        "verify_url": f"/api/v1/verify/{link.token}",
    }


@router.get("/v1/verify/public-key")
async def public_key() -> dict:
    return {"algorithm": "Ed25519", "public_key": pl.public_key_b64(), "encoding": "base64url, raw 32 bytes"}


@router.get("/v1/verify/{token}")
async def verify(token: str, session: SessionDep) -> dict:
    """For recruiters: is this Proof Link genuine and still live? Returns the signed payload so it can be checked
    independently: Ed25519 over the canonical JSON (sorted keys, no spaces) of `payload`."""
    link = (await session.execute(select(ProofLink).where(ProofLink.token == token))).scalar_one_or_none()
    if link is None or not pl.token_ok(link.slug, token):
        return {"valid": False, "reason": "Unknown or altered link"}
    ok = pl.verify_signature(link.payload, link.signature)
    return {
        "valid": ok and link.revoked_at is None, "revoked": link.revoked_at is not None, "payload": link.payload, "signature": link.signature,
        "algorithm": "Ed25519", "public_key": pl.public_key_b64(),
    }


@router.get("/proof-links/{link_id}/views")
async def views(link_id: str, user: UserDep, session: SessionDep) -> list[dict]:
    link = await session.get(ProofLink, link_id)
    if link is None or link.user_id != user.id:
        raise HTTPException(404, "No such link")
    rows = (await session.execute(select(ProofLinkView).where(ProofLinkView.proof_link_id == link.id).order_by(ProofLinkView.viewed_at.desc()).limit(100))).scalars().all()
    return [{"viewed_at": v.viewed_at.isoformat(), "browser": v.ua_family} for v in rows]

"""Your proof-of-skills pack, and its public page."""

import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select

from app.api.deps import RealUserDep, SessionDep, UserDep
from app.models import Profile
from app.schemas import ResumeData
from app.services.consent import grant, has, withdraw
from app.services.evidence import (
    ITEM_KINDS,
    EvidenceError,
    check_item,
    evidenced_skills,
    fetch_codeforces,
    fetch_github,
    new_verify_code,
    public_view,
)
from app.services.ratelimit import hit
from app.sources.base import USER_AGENT
from app.safety import egress

router = APIRouter(tags=["evidence"])


class HandleIn(BaseModel):
    handle: str = Field(min_length=1, max_length=100)


class ItemIn(BaseModel):
    kind: str = Field(default="project")
    title: str = Field(min_length=1, max_length=120)
    url: HttpUrl


class PublicIn(BaseModel):
    public: bool


async def _profile(session, user_id) -> Profile:
    p = (await session.execute(select(Profile).where(Profile.user_id == user_id))).scalar_one()
    return p


async def _out(session, p: Profile) -> dict:
    ev = dict(p.evidence or {})
    public = bool(p.proof_slug) and await has(session, p.user_id, "public_proof")
    return {
        "github": ev.get("github"),
        "codeforces": ev.get("codeforces"),
        "items": ev.get("items", []),
        "verify_code": ev.get("verify_code"),
        "skills": evidenced_skills(ev),
        "public": public,
        "slug": p.proof_slug if public else None,
    }


def _client() -> httpx.AsyncClient:
    return egress.client("evidence", headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@router.get("/evidence")
async def get_evidence(user: UserDep, session: SessionDep) -> dict:
    return await _out(session, await _profile(session, user.id))


@router.put("/evidence/github")
async def link_github(body: HandleIn, user: RealUserDep, session: SessionDep) -> dict:
    await hit("evidence", str(user.id))
    p = await _profile(session, user.id)
    try:
        async with _client() as c:
            gh = await fetch_github(c, body.handle)
    except EvidenceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Couldn't reach GitHub ({type(exc).__name__})") from exc
    ev = dict(p.evidence or {})
    old = ev.get("github") or {}
    gh["verified"] = old.get("verified", False) and old.get("username", "").lower() == gh["username"].lower()
    gh["verified_at"] = old.get("verified_at") if gh["verified"] else None
    ev["github"] = gh
    ev.setdefault("verify_code", new_verify_code())
    p.evidence = ev
    await session.commit()
    return await _out(session, p)


@router.post("/evidence/github/verify")
async def verify_github(user: RealUserDep, session: SessionDep) -> dict:
    """Ownership check: the one-time code must be in the account's public bio right now."""
    await hit("evidence", str(user.id))
    p = await _profile(session, user.id)
    ev = dict(p.evidence or {})
    if not ev.get("github"):
        raise HTTPException(409, "Link your GitHub first")
    async with _client() as c:
        gh = await fetch_github(c, ev["github"]["username"])
    if ev.get("verify_code", "") not in (gh.get("bio") or ""):
        raise HTTPException(400, f"Add {ev.get('verify_code')} to your GitHub bio (github.com/settings/profile), save, then try again.")
    gh["verified"], gh["verified_at"] = True, datetime.now(UTC).isoformat()
    ev["github"] = gh
    p.evidence = ev
    await session.commit()
    return await _out(session, p)


@router.put("/evidence/codeforces")
async def link_codeforces(body: HandleIn, user: RealUserDep, session: SessionDep) -> dict:
    await hit("evidence", str(user.id))
    p = await _profile(session, user.id)
    try:
        async with _client() as c:
            cf = await fetch_codeforces(c, body.handle)
    except EvidenceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Couldn't reach Codeforces") from exc
    p.evidence = {**(p.evidence or {}), "codeforces": cf}
    await session.commit()
    return await _out(session, p)


@router.delete("/evidence/{source}")
async def unlink(source: str, user: RealUserDep, session: SessionDep) -> dict:
    if source not in ("github", "codeforces"):
        raise HTTPException(404, "Unknown source")
    p = await _profile(session, user.id)
    p.evidence = {k: v for k, v in (p.evidence or {}).items() if k != source}
    await session.commit()
    return await _out(session, p)


@router.post("/evidence/items")
async def add_item(body: ItemIn, user: RealUserDep, session: SessionDep) -> dict:
    if body.kind not in ITEM_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(sorted(ITEM_KINDS))}")
    p = await _profile(session, user.id)
    items = list((p.evidence or {}).get("items", []))
    if len(items) >= 20:
        raise HTTPException(409, "Up to 20 items")
    async with _client() as c:
        item = await check_item(c, {"id": secrets.token_hex(4), "kind": body.kind, "title": body.title.strip(), "url": str(body.url), "self_reported": True})
    p.evidence = {**(p.evidence or {}), "items": [*items, item]}
    await session.commit()
    return await _out(session, p)


@router.delete("/evidence/items/{item_id}")
async def remove_item(item_id: str, user: RealUserDep, session: SessionDep) -> dict:
    p = await _profile(session, user.id)
    p.evidence = {**(p.evidence or {}), "items": [i for i in (p.evidence or {}).get("items", []) if i.get("id") != item_id]}
    await session.commit()
    return await _out(session, p)


@router.put("/evidence/public")
async def set_public(body: PublicIn, user: RealUserDep, session: SessionDep) -> dict:
    """Publishing needs the `public_proof` consent; unpublishing withdraws it."""
    p = await _profile(session, user.id)
    if body.public:
        await grant(session, user.id, "public_proof")
        p.proof_slug = p.proof_slug or secrets.token_urlsafe(8).lower().replace("_", "").replace("-", "")[:10]
    else:
        await withdraw(session, user.id, "public_proof")
    await session.commit()
    return await _out(session, p)


@router.get("/public/proof/{slug}")
async def public_proof(slug: str, session: SessionDep) -> dict:
    """The shareable proof page (no sign-in). Evidence only: no email, phone or resume."""
    p = (await session.execute(select(Profile).where(Profile.proof_slug == slug))).scalar_one_or_none()
    if p is None or not await has(session, p.user_id, "public_proof"):
        raise HTTPException(404, "This proof page isn't published")
    resume = ResumeData.model_validate(p.resume or {})
    edu = resume.education[0] if resume.education else None
    headline = " · ".join(x for x in [(edu.degree if edu else ""), (edu.school if edu else "")] if x)
    view = public_view(p.evidence or {}, resume.name or "JobPilot candidate", headline)
    # Entries the student's college verified and the student chose to show: "Verified by <college>". Never stipends.
    from sqlalchemy import text as _text

    rows = (
        await session.execute(
            _text("SELECT a.kind, a.sub_type, a.category, a.title, a.organisation, a.level, a.position, a.start_date, a.end_date, a.ongoing, c.name AS college "
                  "FROM student_achievements a JOIN campuses c ON c.id = a.campus_id WHERE a.user_id = :u AND a.status = 'verified' AND a.show_on_proof_page "
                  "ORDER BY a.start_date DESC NULLS LAST LIMIT 30"),
            {"u": p.user_id},
        )
    ).all()
    view["college_verified"] = [
        {"kind": r.kind, "type": r.sub_type or r.category, "title": r.title, "organisation": r.organisation, "level": r.level, "position": r.position,
         "start": r.start_date.isoformat() if r.start_date else None, "end": r.end_date.isoformat() if r.end_date else None, "ongoing": r.ongoing,
         "verified_by": r.college}
        for r in rows
    ]
    return view

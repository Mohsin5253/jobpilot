"""The Chrome autofill extension's API.

The extension fills an application form on a company's Greenhouse / Lever / Ashby page with your details,
the job's tailored resume and its cover note. It never clicks Submit; when you do, it reports back so the
job moves to Applied. It authenticates with a personal token ("jpx_...") created in Settings.
"""

import re
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import ExtensionUserDep, RealUserDep, SessionDep
from app.api.routes.matches import apply_stage
from app.models import ApiToken, DraftStatus, Job, JobMatch, Profile, Stage
from app.schemas import ResumeData
from app.security import hash_reset_token
from app.services import resume_doc

router = APIRouter(prefix="/extension", tags=["extension"])
MAX_TOKENS = 5


class TokenIn(BaseModel):
    name: str = Field(default="Chrome extension", max_length=80)


class AppliedIn(BaseModel):
    match_id: uuid.UUID


@router.get("/tokens")
async def list_tokens(user: RealUserDep, session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc()))).scalars().all()
    return [{"id": str(t.id), "name": t.name, "prefix": t.prefix, "created_at": t.created_at.isoformat(), "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None} for t in rows]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(body: TokenIn, user: RealUserDep, session: SessionDep) -> dict:
    """The token is shown once; only its hash is stored."""
    count = len(await list_tokens(user, session))
    if count >= MAX_TOKENS:
        raise HTTPException(409, f"You already have {MAX_TOKENS} tokens. Revoke one first.")
    token = "jpx_" + secrets.token_urlsafe(32)
    session.add(ApiToken(user_id=user.id, name=body.name.strip() or "Chrome extension", token_hash=hash_reset_token(token), prefix=token[:10]))
    await session.commit()
    return {"token": token, "prefix": token[:10]}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, user: RealUserDep, session: SessionDep) -> None:
    await session.execute(delete(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user.id))
    await session.commit()


def external_ids(url: str) -> list[tuple[str, str]]:
    """(source, external_id) candidates for an ATS application page URL."""
    u = urlparse(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    out: list[tuple[str, str]] = []
    if "greenhouse.io" in host:
        jid = (parse_qs(u.query).get("gh_jid") or [None])[0] or next((p for p in reversed(parts) if p.isdigit()), None)
        if jid and parts:
            out.append(("greenhouse", f"{parts[0].lower()}:{jid}"))
    elif host == "jobs.lever.co" and len(parts) >= 2:
        out.append(("lever", f"{parts[0].lower()}:{parts[1]}"))
    elif host == "jobs.ashbyhq.com" and len(parts) >= 2:
        out.append(("ashby", f"{parts[0].lower()}:{parts[1]}"))
    return out


def _norm(url: str) -> str:
    u = urlparse(url)
    return f"{u.netloc.lower()}{u.path.rstrip('/')}".removesuffix("/application").removesuffix("/apply")


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


@router.get("/autofill")
async def autofill(user: ExtensionUserDep, session: SessionDep, url: str = Query(max_length=2000)) -> dict:
    """What to put in the form on this page: your details, and for a job JobPilot matched, its tailored draft."""
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
    if profile is None or not profile.resume_text:
        raise HTTPException(409, "Upload your resume in JobPilot first")
    resume = ResumeData.model_validate(profile.resume or {})

    match = None
    ids = external_ids(url)
    conds = [Job.url.ilike(f"%{_norm(url)}%")]
    if ids:
        conds += [(Job.source == s) & (Job.external_id.ilike(e)) for s, e in ids]
    match = (
        await session.execute(
            select(JobMatch).join(Job, Job.id == JobMatch.job_id).where(JobMatch.user_id == user.id, or_(*conds)).options(selectinload(JobMatch.drafts)).limit(1)
        )
    ).unique().scalar_one_or_none()

    links = resume.links
    first, last = _split_name(resume.name or user.name)
    edu = resume.education[0] if resume.education else None
    academics = profile.academics or {}
    applicant = {
        "first_name": first,
        "last_name": last,
        "full_name": resume.name or user.name,
        "email": resume.email or user.email,
        "phone": resume.phone,
        "location": resume.location,
        "linkedin": next((x for x in links if "linkedin.com" in x), ""),
        "github": next((x for x in links if "github.com" in x), ""),
        "website": next((x for x in links if "linkedin.com" not in x and "github.com" not in x), ""),
        "school": (edu.school if edu else "") or academics.get("college", ""),
        "degree": edu.degree if edu else "",
        "graduation_year": str(academics.get("grad_year") or (edu.end if edu else "") or ""),
    }
    if match is None:
        return {"matched": False, "applicant": applicant}
    draft = next((d for d in sorted(match.drafts, key=lambda d: d.created_at) if d.kind == "application" and d.status != DraftStatus.rejected), None)
    proof = f"/p/{profile.proof_slug}" if profile.proof_slug else None
    return {
        "matched": True,
        "match_id": str(match.id),
        "job": {"title": match.job.title, "company": match.job.company, "score": round(match.score)},
        "applicant": applicant,
        "cover_note": re.sub(r"\n{3,}", "\n\n", draft.email_body) if draft else "",
        "resume_path": f"/api/extension/resume/{match.id}",
        "proof_path": proof,
    }


@router.get("/resume/{match_id}")
async def resume_pdf(match_id: uuid.UUID, user: ExtensionUserDep, session: SessionDep) -> Response:
    m = (
        await session.execute(select(JobMatch).where(JobMatch.id == match_id, JobMatch.user_id == user.id).options(selectinload(JobMatch.tailored)))
    ).unique().scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Match not found")
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    doc = resume_doc.build(ResumeData.model_validate(profile.resume or {}), m)
    return Response(resume_doc.render_pdf(doc), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{resume_doc.filename(doc, "pdf")}"'})


@router.post("/applied")
async def applied(body: AppliedIn, user: ExtensionUserDep, session: SessionDep) -> dict:
    """You pressed Submit on the company's form: the job moves to Applied (with the resume version used)."""
    m = (
        await session.execute(select(JobMatch).where(JobMatch.id == body.match_id, JobMatch.user_id == user.id).options(selectinload(JobMatch.drafts)))
    ).unique().scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Match not found")
    apply_stage(m, Stage.applied)
    for d in m.drafts:
        if d.kind == "application" and d.status == DraftStatus.pending:
            d.status = DraftStatus.approved
    await session.commit()
    return {"match_id": str(m.id), "stage": m.stage, "resume_variant": m.resume_variant}

"""India sources (F8): the public source registry, government portals (links only), pasted links, and job-alert
emails the student forwards to their own inbound address."""

import hashlib
import re
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.verifier import apply_verdict
from app.api.deps import AdminDep, RealUserDep, SessionDep
from app.config import settings
from app.logging import log
from app.models import Job, JobMatch, Profile, SourceRegistry, User
from app.schemas import Preferences, ResumeData
from app.services.job_store import store_postings
from app.skills import extract_skills
from app.sources.base import USER_AGENT
from app.sources.india import GOV_PORTALS, alert_links, blocked, fetch_career_page, host_of, publisher_for

router = APIRouter(tags=["sources"])

_ATS = [
    (re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)", re.I), "greenhouse_boards"),
    (re.compile(r"jobs\.lever\.co/([\w-]+)", re.I), "lever_boards"),
    (re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I), "ashby_boards"),
]


class LinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.get("/sources/registry")
async def registry(session: SessionDep) -> list[dict]:
    rows = (await session.execute(select(SourceRegistry).order_by(SourceRegistry.enabled.desc(), SourceRegistry.kind, SourceRegistry.id))).scalars().all()
    return [{"id": r.id, "kind": r.kind, "base_url": r.base_url, "tos_notes": r.tos_notes, "rate_limit_per_min": r.rate_limit_per_min, "enabled": r.enabled} for r in rows]


@router.get("/sources/gov-portals")
async def gov_portals() -> list[dict]:
    return GOV_PORTALS


def _guess(label: str, publisher: str) -> tuple[str, str]:
    """(title, company) from an alert's link text: "Data Analyst Intern at Acme", "Acme - Data Analyst Intern"."""
    label = re.sub(r"\s+", " ", label).strip()
    m = re.match(r"(.+?)\s+(?:at|@)\s+(.+)", label, re.I)
    if m:
        return m.group(1)[:300], m.group(2)[:200]
    m = re.match(r"(.+?)\s+[-|–]\s+(.+)", label)
    if m:
        first, second = m.group(1), m.group(2)
        return (second, first) if re.search(r"intern|engineer|analyst|developer|trainee|associate|designer|marketing", second, re.I) else (first, second)
    return (label or f"{publisher} listing")[:300], publisher


async def save_link(s, user: User, url: str, label: str, source: str) -> JobMatch:
    """A job we keep only as a link (job boards whose terms forbid automation): the student opens it themselves."""
    publisher = publisher_for(url) or host_of(url) or "Link"
    title, company = _guess(label, publisher)
    ext = hashlib.sha256(url.encode()).hexdigest()[:24]
    note = f"Saved from your {publisher} {'alert' if source == 'email_alert' else 'link'}. JobPilot never opens {publisher}: open the link yourself to apply."
    await s.execute(
        insert(Job)
        .values(
            source=source, external_id=ext, company=company, title=title, url=url[:1000], description=note,
            publisher=publisher, apply_links=[{"publisher": publisher, "url": url[:1000], "direct": False}], link_status="unverified",
            dedupe_key=f"{company.lower()}|{title.lower()}|{host_of(url)}"[:300],
        )
        .on_conflict_do_nothing(constraint="uq_jobs_source_external")
    )
    job = (await s.execute(select(Job).where(Job.source == source, Job.external_id == ext))).scalar_one()
    if job.verification_id is None:
        await apply_verdict(s, job, datetime.now(UTC))
    match = (await s.execute(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job.id))).scalar_one_or_none()
    if match is None:
        profile = (await s.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one_or_none()
        have = {x.lower() for x in ResumeData.model_validate((profile.resume if profile else {}) or {}).skills}
        hits = [x for x in extract_skills(title) if x.lower() in have]
        match = JobMatch(user_id=user.id, job_id=job.id, score=min(70.0, 40 + 10 * len(hits)), strengths=hits, explanation=note)
        s.add(match)
        await s.flush()
    return match


@router.post("/sources/link")
async def add_link(body: LinkIn, user: RealUserDep, session: SessionDep) -> dict:
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if blocked(url):
        m = await save_link(session, user, url, "", "user_link")
        await session.commit()
        return {"kind": "link_saved", "match_id": str(m.id), "detail": "Saved as a link. JobPilot never opens this job board; you apply there yourself."}
    profile = (await session.execute(select(Profile).where(Profile.user_id == user.id))).scalar_one()
    prefs = Preferences.model_validate(profile.preferences or {})
    for pat, field in _ATS:
        mt = pat.search(url)
        if mt:
            token = mt.group(1).lower()
            boards = getattr(prefs, field)
            if token not in boards:
                profile.preferences = prefs.model_copy(update={field: [*boards, token]}).model_dump()
                await session.commit()
            return {"kind": "board_added", "board": token, "detail": f"Added {token}'s public job board. New roles there reach your Scout within minutes."}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
        try:
            postings = await fetch_career_page(c, url)
        except httpx.HTTPError:
            postings = []
    if postings:
        await store_postings(postings, datetime.now(UTC))
        if url not in prefs.career_pages:
            profile.preferences = prefs.model_copy(update={"career_pages": [*prefs.career_pages, url][:20]}).model_dump()
        await session.commit()
        return {"kind": "career_page", "found": len(postings), "detail": f"Watching this careers page: {len(postings)} openings found. Checked at most hourly, following the site's robots.txt."}
    m = await save_link(session, user, url, "", "user_link")
    await session.commit()
    return {"kind": "link_saved", "match_id": str(m.id), "detail": "Saved as a link. The page doesn't publish job data we can read, so open it to apply."}


@router.get("/sources/inbound-address")
async def inbound_address(user: RealUserDep, session: SessionDep) -> dict:
    """The private address to forward Internshala / Unstop / Naukri alert emails to."""
    if not settings.inbound_email_domain:
        return {"available": False, "address": None}
    if not user.inbound_token:
        user.inbound_token = secrets.token_hex(6)
        await session.commit()
    return {"available": True, "address": f"alerts+{user.inbound_token}@{settings.inbound_email_domain}"}


def _field(payload: dict, *names: str) -> str:
    for n in names:
        v = payload.get(n)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, list) and v and isinstance(v[0], dict):  # Postmark ToFull
            return v[0].get("Email", "")
    return ""


@router.post("/inbound/email", status_code=202)
async def inbound_email(request: Request, session: SessionDep, secret: str = "") -> dict:
    """Webhook for an inbound-mail provider (Postmark, SendGrid Inbound Parse, Mailgun, Cloudflare Email Workers).
    Keeps only job links from known alert senders, for the student whose alias the mail was sent to."""
    if not settings.inbound_email_secret or not secrets.compare_digest(secret, settings.inbound_email_secret):
        raise HTTPException(403, "Forbidden")
    if request.headers.get("content-type", "").startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        payload = dict(await request.form())
    else:
        payload = await request.json()
    to = _field(payload, "To", "to", "recipient", "ToFull")
    m = re.search(r"alerts\+([0-9a-f]{6,24})@", to, re.I)
    if not m:
        return {"saved": 0}
    user = (await session.execute(select(User).where(User.inbound_token == m.group(1).lower()))).scalar_one_or_none()
    if user is None:
        return {"saved": 0}
    links = alert_links(_field(payload, "TextBody", "text", "body-plain", "plain"), _field(payload, "HtmlBody", "html", "body-html"))
    for url, label in links:
        await save_link(session, user, url, label, "email_alert")
    await session.commit()
    log.info("inbound.alert", links=len(links))  # no addresses or content in logs
    return {"saved": len(links)}


class SourceToggle(BaseModel):
    enabled: bool


@router.put("/admin/sources/{source_id}")
async def toggle_source(source_id: str, body: SourceToggle, _: AdminDep, session: SessionDep) -> dict:
    row = await session.get(SourceRegistry, source_id)
    if row is None:
        raise HTTPException(404, "No such source")
    if row.kind == "blocked" and body.enabled:
        raise HTTPException(409, "Blocked sources can't be enabled: their terms forbid automated access")
    row.enabled = body.enabled
    await session.commit()
    return {"id": row.id, "enabled": row.enabled}

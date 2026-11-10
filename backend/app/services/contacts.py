"""Contact Finder: who to email about a job — real, publicly sourced addresses only.

Sources, all public and all recorded on the contact:
  * the job posting (recruiter emails the company published for this role);
  * the company's own website (careers / contact / about pages, respecting robots.txt);
  * Hunter.io (optional, HUNTER_API_KEY): people at the company filtered by department and seniority.
    Only addresses Hunter *found* on public web pages are kept ("provenance: found", with source
    URLs); pattern-inferred guesses are discarded.
Nothing is ever constructed from a name pattern. Ranking follows the user's preference: a senior person
in the role's own department first, then the posting's recruiter, HR, founders/executives, and finally
the company's careers address.
"""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import session_scope
from app.llm import CallContext, LLMOutputError, LLMUnavailable, get_llm
from app.logging import log
from app.models import CompanyContact, Job
from app.sources.base import USER_AGENT

HUNTER = "https://api.hunter.io/v2"
ATS_OR_FEED = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "themuse.com", "remotive.com", "jobicy.com", "adzuna.", "workable.com",
    "smartrecruiters.com", "myworkdayjobs.com", "linkedin.com", "indeed.", "example.org", "example.com", "wellfound.com",
)
WEBMAIL = ("gmail.com", "yahoo.", "outlook.", "hotmail.", "proton", "icloud.com", "rediffmail.com")
TWO_LEVEL_TLDS = ("co.in", "co.uk", "com.au", "co.jp", "com.sg", "com.br", "org.in", "net.in", "ac.in")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
HIRING_LOCAL = re.compile(r"^(careers?|jobs?|hiring|recruit\w*|talent\w*|hr|people|internships?|campus|joinus|join|apply|resumes?|cv)([._-]|$)", re.I)
CONTACT_LOCAL = re.compile(r"^(hello|contact|hi|info|team)([._-]|$)", re.I)
BAD_LOCAL = re.compile(
    r"(no-?reply|donotreply|privacy|abuse|security|legal|press|media|billing|invoice|dpo|gdpr|unsubscribe|postmaster|"
    r"webmaster|sales|support|help|bugs?|accessib|accommodat|disabilit|\bada\b|eeo|benefits|payroll|fraud|scam|verify|compliance)",
    re.I,
)


def usable_posting_email(email: str | None) -> bool:
    """Addresses in postings are often for accommodations or fraud reports, not applications."""
    return bool(email) and "@" in email and not BAD_LOCAL.search(email.split("@", 1)[0])
PAGES = ("/careers", "/jobs", "/careers/", "/contact", "/contact-us", "/about", "/join-us", "/")

TECH_DEPTS = ("it", "research", "product")
NONTECH_DEPTS = {
    r"market|brand|growth|content|social": "marketing,communication",
    r"sales|business development|account": "sales",
    r"financ|account|payroll": "finance",
    r"recruit|talent|hr|people": "hr",
    r"design|ui|ux": "design",
    r"operation|supply|logistic": "operations",
}


class DomainGuess(BaseModel):
    domain: str


def registrable(host: str) -> str:
    host = host.lower().split(":")[0].strip(".")
    parts = host.split(".")
    keep = 3 if ".".join(parts[-2:]) in TWO_LEVEL_TLDS else 2
    return ".".join(parts[-keep:]) if len(parts) >= keep else host


def _ok_company_domain(domain: str | None) -> bool:
    return bool(domain) and not any(x in domain for x in ATS_OR_FEED) and not any(domain.startswith(w) for w in WEBMAIL)


def _name_tokens(company: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", company.lower())
    return [w for w in words if w not in {"inc", "ltd", "llc", "pvt", "private", "limited", "the", "co", "careers", "jobs", "board"} and len(w) > 2]


async def _homepage_matches(client: httpx.AsyncClient, domain: str, company: str) -> bool:
    """A guessed domain counts only if its live homepage names the company."""
    try:
        r = await client.get(f"https://{domain}/", timeout=8, follow_redirects=True)
    except httpx.HTTPError:
        return False
    if r.status_code >= 400:
        return False
    head = r.text[:60000].lower()
    title = re.search(r"<title[^>]*>(.*?)</title>", head, re.S)
    text = (title.group(1) if title else "") + " " + head[:20000]
    tokens = _name_tokens(company)
    return bool(tokens) and all(t in text for t in tokens[:2])


async def resolve_domain(client: httpx.AsyncClient, job: Job, ctx: CallContext | None) -> str | None:
    if job.company_domain:
        return job.company_domain
    candidates: list[str] = []
    if usable_posting_email(job.recruiter_email):
        candidates.append(registrable(job.recruiter_email.split("@", 1)[1]))
    if job.url:
        candidates.append(registrable(urlparse(job.url).netloc))
    for c in candidates:
        if _ok_company_domain(c):
            return c

    if settings.hunter_api_key:
        try:
            r = await client.get(f"{HUNTER}/domain-search", params={"company": job.company, "limit": 1, "api_key": settings.hunter_api_key}, timeout=15)
            if r.status_code == 200 and _ok_company_domain(d := (r.json().get("data") or {}).get("domain")):
                return d
        except httpx.HTTPError:
            pass

    if not settings.website_contacts_enabled:  # guessing needs live homepage checks
        return None
    guesses: list[str] = []
    try:
        out = await get_llm().structured(
            agent="contacts",
            tier="fast",
            system="Return the official website domain (like stripe.com) of the company. If unsure, return an empty string.",
            prompt=f"Company: {job.company}\nJob posting: {job.url}\nLocation: {job.location}",
            schema=DomainGuess,
            ctx=ctx or CallContext(),
            max_tokens=400,
        )
        if out.domain.strip():
            guesses.append(registrable(re.sub(r"^https?://", "", out.domain.strip()).split("/")[0]))
    except (LLMUnavailable, LLMOutputError):
        pass
    slug = "".join(_name_tokens(job.company))
    # A short, common name ("Flex") matches many unrelated sites, so only the AI's suggestion counts there.
    if slug and len(slug) >= 6:
        guesses += [f"{slug}.{tld}" for tld in ("com", "ai", "in", "io", "co")]
    for g in dict.fromkeys(guesses):
        if _ok_company_domain(g) and await _homepage_matches(client, g, job.company):
            return g
    return None


async def website_contacts(client: httpx.AsyncClient, domain: str) -> list[dict]:
    robots = RobotFileParser()
    try:
        r = await client.get(f"https://{domain}/robots.txt", timeout=6)
        robots.parse(r.text.splitlines() if r.status_code == 200 else [])
    except httpx.HTTPError:
        robots.parse([])
    found: dict[str, dict] = {}
    for path in PAGES:
        url = f"https://{domain}{path}"
        if not robots.can_fetch(USER_AGENT, url):
            continue
        try:
            resp = await client.get(url, timeout=8, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
            continue
        for m in EMAIL.finditer(resp.text[:1_500_000]):
            email = m.group(0).lower().rstrip(".")
            local, _, host = email.partition("@")
            if not (host == domain or host.endswith("." + domain)) or BAD_LOCAL.search(local):
                continue
            if not (HIRING_LOCAL.match(local) or CONTACT_LOCAL.match(local)):
                continue
            entry = found.setdefault(email, {"email": email, "kind": "generic", "source": "website", "sources": []})
            if all(s["uri"] != str(resp.url) for s in entry["sources"]):
                entry["sources"].append({"uri": str(resp.url), "last_seen_on": datetime.now(UTC).date().isoformat()})
        if len(found) >= 4:
            break
    return list(found.values())


def departments_for(job: Job) -> str:
    if job.track == "technical":
        return ",".join((*TECH_DEPTS, "executive", "hr"))
    title = job.title.lower()
    matched = [d for pat, group in NONTECH_DEPTS.items() if re.search(pat, title) for d in group.split(",")]
    return ",".join(dict.fromkeys([*matched, "executive", "hr", "management"]))


async def hunter_people(client: httpx.AsyncClient, domain: str, job: Job) -> list[dict]:
    if not settings.hunter_api_key:
        return []
    params = {
        "domain": domain,
        "type": "personal",
        "seniority": "senior,executive",
        "department": departments_for(job),
        "limit": 10,
        "api_key": settings.hunter_api_key,
    }
    try:
        r = await client.get(f"{HUNTER}/domain-search", params=params, timeout=20)
    except httpx.HTTPError as exc:
        log.warning("contacts.hunter_failed", error=str(exc))
        return []
    if r.status_code != 200:
        log.warning("contacts.hunter_status", status=r.status_code, body=r.text[:200])
        return []
    out = []
    for e in (r.json().get("data") or {}).get("emails", []):
        sources = [{"uri": s.get("uri"), "last_seen_on": s.get("last_seen_on")} for s in e.get("sources") or [] if s.get("uri")]
        # Authentic only: seen on real public pages. Pattern-inferred addresses are dropped.
        if e.get("provenance", "found") != "found" or not sources:
            continue
        out.append(
            {
                "email": e["value"].lower(),
                "kind": "person",
                "first_name": e.get("first_name") or "",
                "last_name": e.get("last_name") or "",
                "position": e.get("position") or "",
                "seniority": e.get("seniority") or "",
                "department": e.get("department") or "",
                "source": "hunter",
                "confidence": int(e.get("confidence") or 0),
                "verification": ((e.get("verification") or {}).get("status")) or "unknown",
                "sources": sources[:8],
                "linkedin": e.get("linkedin"),
            }
        )
    return out


def rank(contacts: list[CompanyContact], job: Job) -> list[CompanyContact]:
    relevant = set(TECH_DEPTS) if job.track == "technical" else set(departments_for(job).split(",")) - {"executive", "hr", "management"}

    def tier(c: CompanyContact) -> int:
        senior = c.seniority in ("senior", "executive")
        if c.kind == "person" and senior and c.department in relevant:
            return 0  # a senior person in the role's own department (e.g. the ML / engineering lead)
        if c.kind == "person" and senior and c.department in ("executive", "management"):
            return 1  # founders / CXOs
        if c.kind == "person" and c.department == "hr":
            return 2  # senior recruiters
        if c.kind == "person":
            return 3
        if c.source == "posting":
            return 4  # the address the company published for this job: CC'd when a person is the recipient
        if HIRING_LOCAL.match(c.email.split("@")[0]):
            return 5
        return 6

    verified = {"valid": 0, "accept_all": 1, "unknown": 2, "": 3}
    return sorted(contacts, key=lambda c: (tier(c), 0 if c.seniority == "executive" else 1, verified.get(c.verification, 3), -c.confidence, -len(c.sources)))


def official_address(ranked: list[CompanyContact]) -> CompanyContact | None:
    """The company's own published hiring inbox (posting recruiter email, else careers@), for CC."""
    generic = [c for c in ranked if c.kind == "generic"]
    return next((c for c in generic if c.source == "posting"), None) or next(
        (c for c in generic if HIRING_LOCAL.match(c.email.split("@")[0])), None
    )


async def find_contacts(job: Job, ctx: CallContext | None = None, force: bool = False) -> list[CompanyContact]:
    """Ranked real contacts for the job's company (cached per domain for settings.contacts_cache_days)."""
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        domain = await resolve_domain(client, job, ctx)
        if domain and domain != job.company_domain:
            async with session_scope() as s:
                await s.execute(update(Job).where(Job.company == job.company, Job.company_domain.is_(None)).values(company_domain=domain))
            job.company_domain = domain

        rows: list[dict] = []
        async with session_scope() as s:
            posted = (
                await s.execute(
                    select(Job.recruiter_email, Job.url).where(
                        Job.recruiter_email.is_not(None),
                        (Job.company == job.company) | (Job.company_domain == domain) if domain else (Job.company == job.company),
                    )
                )
            ).all()
        today = datetime.now(UTC).date().isoformat()
        for email, url in {(e.lower(), u) for e, u in [*posted, (job.recruiter_email, job.url)] if usable_posting_email(e)}:
            if domain is None or email.endswith("@" + domain) or email.endswith("." + domain):
                rows.append({"email": email, "kind": "generic", "source": "posting", "sources": [{"uri": url, "last_seen_on": today}]})
        if domain:
            async with session_scope() as s:
                cached = (await s.execute(select(CompanyContact).where(CompanyContact.domain == domain))).scalars().all()
            fresh = cached and all(c.fetched_at > datetime.now(UTC) - timedelta(days=settings.contacts_cache_days) for c in cached)
            if force or not fresh:
                site, people = await asyncio.gather(
                    website_contacts(client, domain) if settings.website_contacts_enabled else asyncio.sleep(0, result=[]),
                    hunter_people(client, domain, job),
                )
                rows += site + people

        if rows:
            async with session_scope() as s:
                for r in rows:
                    stmt = insert(CompanyContact).values(id=uuid.uuid4(), domain=domain or registrable(r["email"].split("@")[1]), company=job.company, **r)
                    await s.execute(
                        stmt.on_conflict_do_update(
                            constraint="uq_contact_domain_email",
                            set_={k: getattr(stmt.excluded, k) for k in ("kind", "first_name", "last_name", "position", "seniority", "department", "confidence", "verification", "sources", "linkedin", "fetched_at") if k in r or k == "fetched_at"},
                        )
                    )

        if not domain and not usable_posting_email(job.recruiter_email):
            return []
        async with session_scope() as s:
            q = select(CompanyContact)
            if domain:
                q = q.where(CompanyContact.domain == domain)
            else:
                q = q.where(CompanyContact.email == job.recruiter_email.lower())
            contacts = list((await s.execute(q)).scalars().all())
    return rank(contacts, job)

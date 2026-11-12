"""India sources without ToS-violating scraping (F8).

* Company career pages: a watcher that reads only the schema.org JobPosting data a page publishes for search
  engines (JSON-LD), after checking robots.txt, at most one request per minute per domain, cached.
* GitHub internship repositories (e.g. SimplifyJobs): their public listings JSON.
* Government portals: deep links only (never fetched).
* Job-board alert emails the student forwards, and links they paste: kept as links they open themselves.

Never fetched, logged into or automated: LinkedIn, Internshala, Naukri, Unstop, Indeed, Glassdoor, Wellfound.
"""

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings
from app.logging import log
from app.schemas import Preferences
from app.sources.base import USER_AGENT, Posting, clean_company, get_json, html_to_text

# Job boards whose terms forbid automated access: we never fetch these, only keep links the student opens.
BLOCKED_HOSTS = ("linkedin.com", "internshala.com", "naukri.com", "unstop.com", "indeed.com", "indeed.co.in", "glassdoor.com", "glassdoor.co.in", "wellfound.com", "angel.co", "foundit.in", "shine.com")
ALERT_PUBLISHERS = {"internshala.com": "Internshala", "unstop.com": "Unstop", "naukri.com": "Naukri", "linkedin.com": "LinkedIn", "foundit.in": "foundit"}

# Official portals, linked (never fetched).
GOV_PORTALS = [
    {"name": "PM Internship Scheme", "url": "https://pminternship.mca.gov.in", "note": "Ministry of Corporate Affairs. Free to apply."},
    {"name": "AICTE Internship Portal", "url": "https://internship.aicte-india.org", "note": "Internships listed by AICTE for students of approved institutions."},
    {"name": "National Apprenticeship Training Scheme (NATS)", "url": "https://nats.education.gov.in", "note": "Ministry of Education apprenticeships with a stipend."},
]

DOMAIN_GAP_S = 60  # at most one request per minute per domain
ROBOTS_TTL_S = 24 * 3600
_last_hit: dict[str, float] = {}
_robots: dict[str, tuple[float, RobotFileParser | None]] = {}


def host_of(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def blocked(url: str) -> bool:
    h = host_of(url)
    return any(h == b or h.endswith("." + b) for b in BLOCKED_HOSTS)


def publisher_for(url: str) -> str | None:
    h = host_of(url)
    return next((name for dom, name in ALERT_PUBLISHERS.items() if h == dom or h.endswith("." + dom)), None)


async def robots_allows(client: httpx.AsyncClient, url: str) -> bool:
    """robots.txt for our user agent, cached a day. An unreachable robots.txt means allowed (the standard); a 401/403
    on it means everything is disallowed."""
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots.get(origin)
    if cached is None or cached[0] < time.monotonic():
        rp: RobotFileParser | None = RobotFileParser()
        try:
            r = await client.get(f"{origin}/robots.txt", timeout=10)
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.allow_all = True
        except httpx.HTTPError:
            rp = None
        _robots[origin] = (time.monotonic() + ROBOTS_TTL_S, rp)
        cached = _robots[origin]
    rp = cached[1]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def throttled(url: str) -> bool:
    """True when this domain was fetched less than a minute ago (the caller skips; the next tick retries)."""
    h = host_of(url)
    now = time.monotonic()
    if now - _last_hit.get(h, -1e9) < DOMAIN_GAP_S:
        return True
    _last_hit[h] = now
    return False


_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        types = node.get("@type")
        if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
            yield node
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in node:
                yield from _walk(node[key])


def _location(jp: dict) -> tuple[str, bool]:
    remote = str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    locs = jp.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    names = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, dict):
            country = addr.get("addressCountry")
            country = country.get("name") if isinstance(country, dict) else country
            names.append(", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion"), country] if x))
    return (" · ".join(n for n in names if n) or ("Remote" if remote else "")), remote


def _salary(jp: dict) -> tuple[float | None, float | None]:
    v = ((jp.get("baseSalary") or {}).get("value")) if isinstance(jp.get("baseSalary"), dict) else None
    if isinstance(v, dict):
        lo, hi = v.get("minValue") or v.get("value"), v.get("maxValue") or v.get("value")
        try:
            return (float(lo) if lo else None, float(hi) if hi else None)
        except (TypeError, ValueError):
            return None, None
    return None, None


def parse_jobpostings(html: str, page_url: str) -> list[Posting]:
    out: list[Posting] = []
    for block in _LD.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for jp in _walk(data):
            title = html_to_text(str(jp.get("title") or "")).strip()
            if not title:
                continue
            org = jp.get("hiringOrganization") or {}
            company = clean_company((org.get("name") if isinstance(org, dict) else str(org)) or host_of(page_url))
            url = urljoin(page_url, str(jp.get("url") or page_url))
            ident = jp.get("identifier")
            ident = ident.get("value") if isinstance(ident, dict) else ident
            location, remote = _location(jp)
            lo, hi = _salary(jp)
            posted = None
            try:
                posted = datetime.fromisoformat(str(jp.get("datePosted"))[:19]).replace(tzinfo=UTC) if jp.get("datePosted") else None
            except ValueError:
                pass
            out.append(
                Posting(
                    source="career_page",
                    external_id=hashlib.sha1(f"{host_of(page_url)}|{ident or url}|{title}".encode()).hexdigest()[:24],
                    company=company,
                    title=title[:300],
                    location=location,
                    remote=remote,
                    url=url,
                    description=html_to_text(str(jp.get("description") or "")),
                    salary_min=lo,
                    salary_max=hi,
                    posted_at=posted,
                    publisher="Company site",
                    company_domain=host_of(page_url),
                    extra={"entry_level": bool(re.search(r"intern|trainee|graduate|fresher|entry", f"{title} {jp.get('employmentType', '')}", re.I))},
                )
            )
    return out


async def fetch_career_page(client: httpx.AsyncClient, url: str) -> list[Posting]:
    """robots.txt first (cached a day), then at most one page request a minute per domain, shared across replicas by
    the egress gate (a domain fetched in the last minute is skipped; the next tick retries)."""
    from app.safety import egress

    with egress.purpose("career_page"):
        try:
            return await _fetch_career_page(client, url)
        except egress.EgressDenied as exc:
            log.info("career_page.skipped", host=host_of(url), rule=exc.rule)
            return []


async def _fetch_career_page(client: httpx.AsyncClient, url: str) -> list[Posting]:
    if blocked(url) or not url.startswith(("http://", "https://")):
        return []
    if not await robots_allows(client, url):
        log.info("career_page.robots_disallow", host=host_of(url))
        return []
    if throttled(url):
        return []
    r = await client.get(url, timeout=settings.source_timeout_s, follow_redirects=True)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "") or blocked(str(r.url)):
        return []
    return parse_jobpostings(r.text[:2_000_000], str(r.url))


class CareerPageSource:
    """One target per careers page URL a student watches."""

    name = "career_page"
    min_interval_minutes = 60  # career pages change slowly; also the per-domain gap above

    def enabled(self, prefs: Preferences) -> bool:
        return bool(prefs.career_pages)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        out: list[Posting] = []
        for url in prefs.career_pages[:1]:  # one page per target
            out += await fetch_career_page(client, url)
        return out


class GitHubListingsSource:
    """Community-maintained internship lists on GitHub (public JSON, e.g. SimplifyJobs)."""

    name = "github_listings"
    min_interval_minutes = 360

    def enabled(self, prefs: Preferences) -> bool:
        return settings.public_feeds_enabled and prefs.public_job_feeds and bool(settings.github_listings_urls)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        out: list[Posting] = []
        for url in settings.github_listings_urls:
            try:
                rows = await get_json(client, url)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("github_listings.failed", url=url, error=str(exc)[:200])
                continue
            for r in rows if isinstance(rows, list) else []:
                if not r.get("active", True) or not r.get("is_visible", True) or not r.get("url"):
                    continue
                locs = r.get("locations") or []
                posted = r.get("date_posted")
                out.append(
                    Posting(
                        source=self.name,
                        external_id=str(r.get("id") or hashlib.sha1(r["url"].encode()).hexdigest()[:24]),
                        company=clean_company(r.get("company_name") or "Unknown"),
                        title=str(r.get("title") or "").strip()[:300],
                        location=" · ".join(locs),
                        remote=any("remote" in str(x).lower() for x in locs),
                        url=r["url"],
                        description=f"{r.get('title', '')} at {r.get('company_name', '')}. Terms: {', '.join(r.get('terms') or [])}. Listed in a community-maintained GitHub internship list.",
                        posted_at=datetime.fromtimestamp(posted, UTC) if isinstance(posted, (int, float)) else None,
                        publisher="GitHub list",
                        extra={"entry_level": True},
                    )
                )
        return out


_A = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def alert_links(text: str, html: str = "") -> list[tuple[str, str]]:
    """(url, label) pairs for job links in a forwarded alert email. Tracking redirects are kept as-is: we never
    open them, the student does."""
    found: dict[str, str] = {}
    for href, label in _A.findall(html or ""):
        clean = html_to_text(label).strip()
        if publisher_for(href) and clean and len(clean) > 3:
            found.setdefault(href, clean[:200])
    for url in _URL.findall(text or ""):
        if publisher_for(url):
            found.setdefault(url, "")
    return list(found.items())[:30]

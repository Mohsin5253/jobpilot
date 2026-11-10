"""Job sources. Only official / public APIs, no scraping (and no LinkedIn):

  * Company career boards: Greenhouse, Lever and Ashby public job-board APIs. These list only open
    roles, so everything they return is live.
  * Public feeds: The Muse (internships + entry level, tech and non-tech), Remotive and Jobicy
    (remote). Their terms ask for attribution and links back to the original posting; the UI shows
    "via <source>" and every apply button goes to the source URL.
  * Adzuna search API (needs a free key; strong India coverage).
  * Demo feed of fictional postings, off by default (tests / offline demos).
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from urllib.parse import urlparse

import httpx

from app.config import settings
from app.schemas import Preferences
from app.sources.base import INDIA_PLACES, Posting, find_recruiter_email, get_json, html_to_text, location_ok
from app.sources.base import classify_track, clean_company, is_early_career

REMOTE_WORDS = ("remote", "anywhere", "work from home", "wfh", "flexible")
BOARD_CONCURRENCY = 8


def _is_remote(*parts: str) -> bool:
    joined = " ".join(p or "" for p in parts).lower()
    return any(w in joined for w in REMOTE_WORDS)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def title_location_ok(title: str, location: str, remote: bool, prefs: Preferences) -> bool:
    """Cheap pre-filter before downloading a full description."""
    if prefs.internships_only and not is_early_career(title):
        return False
    if classify_track(title) not in prefs.tracks:
        return False
    return location_ok(Posting(source="", external_id="", company="", title=title, location=location, remote=remote), prefs)


async def _gather_boards(tokens: list[str], fetch_one) -> list[Posting]:
    sem = asyncio.Semaphore(BOARD_CONCURRENCY)

    async def guarded(token: str) -> list[Posting]:
        async with sem:
            return await fetch_one(token.strip())

    results = await asyncio.gather(*(guarded(t) for t in tokens[:40] if t.strip()), return_exceptions=True)
    out: list[Posting] = []
    for res in results:
        if isinstance(res, list):
            out += res
    # Every board failing means something systemic (network, API change): let the Scout report it.
    if tokens and results and all(isinstance(r, BaseException) for r in results):
        raise results[0]  # type: ignore[misc]
    return out


def _monthly_gap(monthly: int) -> int:
    """Minutes between requests so the whole service stays within a monthly request quota. The ingester
    spends that one budget for everyone, on the searches the most users want."""
    return max(10, int(30 * 24 * 60 / max(monthly, 1)))


def role_queries(prefs: Preferences, skills: list[str] | None) -> list[str]:
    """Searches built from the resume: one per role family its skills point to (generic "fresher jobs"
    searches mostly return bulk listings, and quota-limited APIs charge per request)."""
    if prefs.keywords:
        return list(prefs.keywords)
    level = "intern" if prefs.internships_only else "fresher"
    have = " | ".join(skills or []).lower()
    roles = [role for role, words in ROLE_FAMILIES if any(w in have for w in words)]
    if "technical" in prefs.tracks and not roles:
        roles = ["software developer"]
    if "non_technical" in prefs.tracks:
        roles += NON_TECH_ROLES
    return [f"{role} {level}" for role in roles] or [level]


class AdzunaSource:
    """Adzuna's job index for India (aggregates Indian job boards and employer sites). Needs a free
    developer key; one search per fetch, rotated across the resume's role families. Shown as "Jobs by Adzuna"."""

    name = "adzuna"
    quota_limited = True
    BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    @property
    def min_interval_minutes(self) -> int:
        return _monthly_gap(settings.adzuna_monthly_requests)

    def enabled(self, prefs: Preferences) -> bool:
        return bool(settings.adzuna_app_id and settings.adzuna_app_key)

    def queries(self, prefs: Preferences, skills: list[str] | None = None) -> list[str]:
        return role_queries(prefs, skills)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences, query: str | None = None) -> list[Posting]:
        out: dict[str, Posting] = {}
        where_list = [loc for loc in prefs.locations if loc.lower() not in ("remote", "india", prefs.adzuna_country)] or [""]
        for what in [query or self.queries(prefs)[0]]:
            for where in where_list[:1]:
                params = {
                    "app_id": settings.adzuna_app_id,
                    "app_key": settings.adzuna_app_key,
                    "what": what,
                    "results_per_page": min(prefs.max_jobs_per_source, 50),
                    "max_days_old": prefs.max_age_days,
                    "sort_by": "date",
                    "content-type": "application/json",
                }
                if where:
                    params["where"] = where
                data = await get_json(client, self.BASE.format(country=prefs.adzuna_country), params)
                for r in data.get("results", []):
                    desc = html_to_text(r.get("description", ""))
                    loc = (r.get("location") or {}).get("display_name", "")
                    if prefs.adzuna_country == "in" and loc and not INDIA_PLACES.search(loc):
                        loc = f"{loc}, India"
                    out[str(r["id"])] = Posting(
                        source=self.name,
                        external_id=str(r["id"]),
                        company=(r.get("company") or {}).get("display_name", "Unknown"),
                        title=r.get("title", "").strip(),
                        location=loc,
                        remote=_is_remote(loc, r.get("title", ""), desc[:500]),
                        url=r.get("redirect_url", ""),
                        description=desc,
                        salary_min=r.get("salary_min"),
                        salary_max=r.get("salary_max"),
                        posted_at=_parse_dt(r.get("created")),
                        publisher="Adzuna",
                        apply_links=[{"publisher": "Adzuna", "url": r.get("redirect_url", ""), "direct": False}] if r.get("redirect_url") else [],
                    )
        return list(out.values())


class GreenhouseSource:
    name = "greenhouse"
    min_interval_minutes = 2  # public, CDN-cached board JSON: new roles show up within minutes
    BASE = "https://boards-api.greenhouse.io/v1/boards/{token}"

    def enabled(self, prefs: Preferences) -> bool:
        return bool(prefs.greenhouse_boards)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        async def board(token: str) -> list[Posting]:
            # Two phases: the list is small; descriptions are fetched only for roles that pass the filters.
            listing = await get_json(client, f"{self.BASE.format(token=token)}/jobs")
            company = token.replace("-", " ").title()
            keep = [
                j for j in listing.get("jobs", [])
                if title_location_ok(j.get("title", ""), (j.get("location") or {}).get("name", ""), _is_remote((j.get("location") or {}).get("name", "")), prefs)
            ][: prefs.max_jobs_per_source]
            details = await asyncio.gather(
                *(get_json(client, f"{self.BASE.format(token=token)}/jobs/{j['id']}") for j in keep), return_exceptions=True
            )
            out = []
            for j, d in zip(keep, details):
                content = d.get("content", "") if isinstance(d, dict) else ""
                desc = html_to_text(content)
                loc = (j.get("location") or {}).get("name", "")
                out.append(
                    Posting(
                        source=self.name,
                        external_id=f"{token}:{j['id']}",
                        company=clean_company((d.get("company_name") if isinstance(d, dict) else None) or j.get("company_name") or company),
                        title=j.get("title", "").strip(),
                        location=loc,
                        remote=_is_remote(loc, j.get("title", "")),
                        url=j.get("absolute_url", ""),
                        description=desc,
                        recruiter_email=find_recruiter_email(desc),
                        posted_at=_parse_dt(j.get("first_published") or j.get("updated_at")),
                    )
                )
            return out

        return await _gather_boards(prefs.greenhouse_boards, board)


class LeverSource:
    name = "lever"
    min_interval_minutes = 2  # public, CDN-cached board JSON: new roles show up within minutes
    BASE = "https://api.lever.co/v0/postings/{company}"

    def enabled(self, prefs: Preferences) -> bool:
        return bool(prefs.lever_boards)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        async def board(company: str) -> list[Posting]:
            data = await get_json(client, self.BASE.format(company=company), {"mode": "json"})
            out = []
            for j in data:
                cats = j.get("categories") or {}
                loc = cats.get("location", "") or ""
                remote = j.get("workplaceType") == "remote" or _is_remote(loc)
                if not title_location_ok(j.get("text", ""), loc, remote, prefs):
                    continue
                lists = "\n".join(f"{lst.get('text', '')}\n{html_to_text(lst.get('content', ''))}" for lst in j.get("lists", []))
                desc = "\n\n".join(x for x in (j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")) if x)
                created = j.get("createdAt")
                out.append(
                    Posting(
                        source=self.name,
                        external_id=f"{company}:{j['id']}",
                        company=company.replace("-", " ").title(),
                        title=j.get("text", "").strip(),
                        location=loc,
                        remote=remote,
                        url=j.get("hostedUrl", ""),
                        description=desc,
                        recruiter_email=find_recruiter_email(desc),
                        posted_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
                    )
                )
            return out[: prefs.max_jobs_per_source]

        return await _gather_boards(prefs.lever_boards, board)


class AshbySource:
    name = "ashby"
    min_interval_minutes = 2  # public, CDN-cached board JSON: new roles show up within minutes
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{org}"

    def enabled(self, prefs: Preferences) -> bool:
        return bool(prefs.ashby_boards)

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        async def board(org: str) -> list[Posting]:
            data = await get_json(client, self.BASE.format(org=org))
            out = []
            for j in data.get("jobs", []):
                if j.get("isListed") is False:
                    continue
                locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
                loc = " · ".join(x for x in locs if x)
                remote = bool(j.get("isRemote")) or j.get("workplaceType") == "Remote"
                title = j.get("title", "").strip()
                if j.get("employmentType") == "Intern" and not is_early_career(title):
                    title = f"{title} (Intern)"
                if not title_location_ok(title, loc, remote, prefs):
                    continue
                desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
                out.append(
                    Posting(
                        source=self.name,
                        external_id=f"{org}:{j['id']}",
                        company=org.replace("-", " ").title(),
                        title=title,
                        location=loc,
                        remote=remote,
                        url=j.get("jobUrl") or j.get("applyUrl", ""),
                        description=desc,
                        recruiter_email=find_recruiter_email(desc),
                        posted_at=_parse_dt(j.get("publishedAt")),
                    )
                )
            return out[: prefs.max_jobs_per_source]

        return await _gather_boards(prefs.ashby_boards, board)


class _PublicFeed:
    def enabled(self, prefs: Preferences) -> bool:
        return settings.public_feeds_enabled and prefs.public_job_feeds


INDIAN_CITIES_MUSE = ["Bengaluru, India", "Mumbai, India", "Hyderabad, India", "New Delhi, India", "Pune, India", "Chennai, India", "Gurgaon, India", "Noida, India"]
MUSE_TECH_CATEGORIES = {"Software Engineering", "Data and Analytics", "Data Science", "IT", "Science and Engineering", "Computer and IT"}


class MuseSource(_PublicFeed):
    name = "themuse"
    min_interval_minutes = 15
    BASE = "https://www.themuse.com/api/public/jobs"

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        params: list[tuple[str, str]] = [("level", "Internship"), ("level", "Entry Level")]
        for loc in prefs.locations:
            if loc.lower() == "india":
                params += [("location", c) for c in INDIAN_CITIES_MUSE]
            elif loc.lower() == "remote":
                params.append(("location", "Flexible / Remote"))
            else:
                params.append(("location", loc))
        out: dict[str, Posting] = {}
        for page in range(3):
            data = await get_json(client, self.BASE, [*params, ("page", str(page))])
            for j in data.get("results", []):
                locs = [x.get("name", "") for x in j.get("locations", [])]
                levels = {x.get("name", "") for x in j.get("levels", [])}
                out[str(j["id"])] = Posting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=(j.get("company") or {}).get("name", "Unknown"),
                    title=j.get("name", "").strip(),
                    location=" · ".join(locs),
                    remote=any("remote" in x.lower() for x in locs),
                    url=(j.get("refs") or {}).get("landing_page", ""),
                    description=html_to_text(j.get("contents", "")),
                    posted_at=_parse_dt(j.get("publication_date")),
                    extra={"entry_level": bool(levels & {"Internship", "Entry Level"})},
                )
            if page + 1 >= data.get("page_count", 0):
                break
        return list(out.values())


class RemotiveSource(_PublicFeed):
    name = "remotive"
    min_interval_minutes = 360  # Remotive asks API users to keep volume low
    BASE = "https://remotive.com/api/remote-jobs"

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        if prefs.locations and not any(x.lower() == "remote" for x in prefs.locations):
            return []
        out: dict[str, Posting] = {}
        # Remotive asks API users to keep request volume low: two searches per run.
        for query in (["intern", "junior"] if prefs.internships_only else ["junior", "entry level"]):
            data = await get_json(client, self.BASE, {"search": query, "limit": 100})
            for j in data.get("jobs", []):
                out[str(j["id"])] = Posting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=j.get("company_name", "Unknown"),
                    title=j.get("title", "").strip(),
                    location=j.get("candidate_required_location", "") or "Worldwide",
                    remote=True,
                    url=j.get("url", ""),
                    description=html_to_text(j.get("description", "")),
                    posted_at=_parse_dt(j.get("publication_date")),
                    extra={"entry_level": j.get("job_type") == "internship"},
                )
        return list(out.values())


class JobicySource(_PublicFeed):
    name = "jobicy"
    min_interval_minutes = 60
    BASE = "https://jobicy.com/api/v2/remote-jobs"

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        if prefs.locations and not any(x.lower() == "remote" for x in prefs.locations):
            return []
        data = await get_json(client, self.BASE, {"count": 100})
        out = []
        for j in data.get("jobs", []):
            level = (j.get("jobLevel") or "").lower()
            out.append(
                Posting(
                    source=self.name,
                    external_id=str(j["id"]),
                    company=html_to_text(j.get("companyName", "Unknown")),
                    title=html_to_text(j.get("jobTitle", "")).strip(),
                    location=j.get("jobGeo", "") or "Anywhere",
                    remote=True,
                    url=j.get("url", ""),
                    description=html_to_text(j.get("jobDescription", "") or j.get("jobExcerpt", "")),
                    posted_at=_parse_dt((j.get("pubDate") or "").replace(" ", "T")),
                    extra={"entry_level": level in ("entry", "junior", "internship")},
                )
            )
        return out


PUBLISHER_ALIASES = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor", "naukri": "Naukri", "wellfound": "Wellfound", "angellist": "Wellfound"}


def _publisher(name: str | None) -> str | None:
    if not name:
        return None
    low = name.lower()
    return next((v for k, v in PUBLISHER_ALIASES.items() if k in low), name.strip())


def jsearch_jobs(payload: dict) -> list[dict]:
    """JSearch v4 returned {"data": [jobs]}; v5 returns {"data": {"cursor": ..., <jobs list>}}.
    Accept either: the job list is the first list of objects that carry job_id / job_title."""
    data = payload.get("data")
    if isinstance(data, list):
        return [j for j in data if isinstance(j, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and ("job_id" in value[0] or "job_title" in value[0]):
                return value
    return []


class JSearchSource:
    """Google for Jobs index via the JSearch API: postings from LinkedIn, Indeed, Glassdoor, Naukri,
    Wellfound and company career sites, with every board's apply link. Needs JSEARCH_API_KEY."""

    name = "jsearch"
    quota_limited = True
    RAPIDAPI = "https://jsearch.p.rapidapi.com"
    OPENWEBNINJA = "https://api.openwebninja.com/jsearch"
    # During the v5 rollout the gateway answers 404 "Endpoint does not exist" on one of these paths
    # and serves the other, and which one flips; try the last one that worked first.
    PATHS = ["/search", "/search-v2"]
    _path_ok = "/search"
    _lock = asyncio.Lock()  # one request at a time: concurrent calls get 429 from the free plan
    _last_call = 0.0

    @property
    def min_interval_minutes(self) -> int:
        # The monthly quota, spread evenly: one request per fetch, shared by every user.
        return max(30, _monthly_gap(settings.jsearch_monthly_requests))

    def enabled(self, prefs: Preferences) -> bool:
        return bool(settings.jsearch_api_key)

    def queries(self, prefs: Preferences, skills: list[str] | None = None) -> list[str]:
        where = "India" if any(x.lower() == "india" for x in prefs.locations) or not prefs.locations else prefs.locations[0]
        return [f"{q} in {where}" for q in role_queries(prefs, skills)]

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences, query: str | None = None) -> list[Posting]:
        if settings.jsearch_provider == "openwebninja":
            base, headers = self.OPENWEBNINJA, {"x-api-key": settings.jsearch_api_key or ""}
        else:
            base, headers = self.RAPIDAPI, {"X-RapidAPI-Key": settings.jsearch_api_key or "", "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        params = {
            "query": query or self.queries(prefs)[0],
            "num_pages": "1",  # one page = 10 results = 1 request credit
            "country": prefs.adzuna_country or "in",
            "date_posted": "week" if prefs.max_age_days <= 7 else "month",
        }
        # No job_requirements filter: JSearch returns nothing for "intern" searches with it; the Scout's
        # own early-career check does that job.
        paths = [JSearchSource._path_ok] + [p for p in self.PATHS if p != JSearchSource._path_ok]
        async with JSearchSource._lock:
            wait = JSearchSource._last_call + 1.2 - time.monotonic()  # stay under the per-second limit
            if wait > 0:
                await asyncio.sleep(wait)
            JSearchSource._last_call = time.monotonic()
            for path in paths:
                resp = await client.get(base + path, params=params, headers=headers, timeout=settings.source_timeout_s + 10)
                if resp.status_code == 404 and "does not exist" in resp.text:
                    continue  # not served on this path right now: costs no request credit
                JSearchSource._path_ok = path
                break
        resp.raise_for_status()
        out = []
        for j in jsearch_jobs(resp.json()):
            if not j.get("job_id") or not j.get("job_title"):
                continue
            # "IN" is spelled out: small towns aren't in the India place list, and "IN" alone reads as Indiana.
            country = "India" if (j.get("job_country") or "").upper() == "IN" else j.get("job_country")
            loc = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), country) if x)
            links = [
                {"publisher": _publisher(a.get("publisher")), "url": a.get("apply_link"), "direct": bool(a.get("is_direct"))}
                for a in j.get("apply_options") or []
                if a.get("apply_link")
            ] or ([{"publisher": _publisher(j.get("job_publisher")), "url": j.get("job_apply_link"), "direct": bool(j.get("job_apply_is_direct"))}] if j.get("job_apply_link") else [])
            site = j.get("employer_website") or ""
            domain = None
            if site:
                from app.services.contacts import _ok_company_domain, registrable

                host = urlparse(site if "://" in site else f"https://{site}").netloc
                domain = registrable(host) if host and _ok_company_domain(registrable(host)) else None
            desc = j.get("job_description") or ""
            out.append(
                Posting(
                    source=self.name,
                    external_id=str(j["job_id"])[:200],
                    company=(j.get("employer_name") or "").strip(),
                    title=j["job_title"].strip(),
                    location=loc or ("Remote" if j.get("job_is_remote") else ""),
                    remote=bool(j.get("job_is_remote")),
                    url=j.get("job_apply_link") or (links[0]["url"] if links else ""),
                    description=desc,
                    salary_min=j.get("job_min_salary"),
                    salary_max=j.get("job_max_salary"),
                    recruiter_email=find_recruiter_email(desc),
                    posted_at=_parse_dt(j.get("job_posted_at_datetime_utc")),
                    publisher=_publisher(j.get("job_publisher")),
                    apply_links=links,
                    company_domain=domain,
                    # v4 sent "INTERN"; v5 sends "Internship" plus a job_employment_types list.
                    extra={"entry_level": any("intern" in (t or "").lower() for t in [j.get("job_employment_type"), *(j.get("job_employment_types") or [])])},
                )
            )
        return collapse_bulk(out)


def collapse_bulk(postings: list[Posting], limit: int = 3) -> list[Posting]:
    """Some employers post one generic ad in dozens of towns ("Entry-Level Jobs" x 8 villages). Keep the
    first copy of a company + title seen in `limit` or more places and note how many places it covers."""
    groups: dict[tuple[str, str], list[Posting]] = {}
    for p in postings:
        groups.setdefault((p.company.lower(), p.title.lower()), []).append(p)
    out = []
    for p in postings:
        same = groups[(p.company.lower(), p.title.lower())]
        if len(same) < limit:
            out.append(p)
        elif p is same[0]:
            p.location = f"{p.location} (+{len(same) - 1} more locations)"
            out.append(p)
    return out


ROLE_FAMILIES = [
    ("machine learning", ("machine learning", "deep learning", "scikit", "pytorch", "tensorflow", "reinforcement")),
    ("generative AI", ("llm", "rag", "agents", "embeddings", "langchain", "generative")),
    ("data science", ("pandas", "numpy", "statistics", "data science")),
    ("data analyst", ("sql", "excel", "power bi", "tableau", "matplotlib", "seaborn")),
    ("python developer", ("flask", "fastapi", "django")),
    ("software developer", ("javascript", "react", "node", "java", "c++", "data structures")),
]
NON_TECH_ROLES = ["business analyst", "marketing"]


class DemoSource:
    """Bundled sample postings (fictional companies) for tests and offline demos. Off by default."""

    name = "demo"
    min_interval_minutes = 0
    PATH = Path(__file__).resolve().parent.parent / "data" / "demo_jobs.json"

    def enabled(self, prefs: Preferences) -> bool:
        return settings.demo_source

    async def fetch(self, client: httpx.AsyncClient, prefs: Preferences) -> list[Posting]:
        rows = json.loads(self.PATH.read_text())
        now = datetime.now(UTC)
        return [
            Posting(
                source=self.name,
                external_id=r["id"],
                company=r["company"],
                title=r["title"],
                location=r["location"],
                remote=r.get("remote", False),
                url=r.get("url", ""),
                description=r["description"],
                recruiter_email=r.get("recruiter_email"),
                salary_min=r.get("salary_min"),
                salary_max=r.get("salary_max"),
                posted_at=now - timedelta(days=i % 9),
            )
            for i, r in enumerate(rows)
        ]


from app.sources.india import CareerPageSource, GitHubListingsSource  # noqa: E402

ALL_SOURCES = [
    JSearchSource(),
    CareerPageSource(),
    GitHubListingsSource(),
    GreenhouseSource(),
    LeverSource(),
    AshbySource(),
    MuseSource(),
    RemotiveSource(),
    JobicySource(),
    AdzunaSource(),
    DemoSource(),
]

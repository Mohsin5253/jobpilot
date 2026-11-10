"""Authenticity checks for postings from aggregators (JSearch, Adzuna, The Muse, Remotive, Jobicy).

  * looks_legit: drops scam patterns (fees, deposits, "earn per day", WhatsApp/Telegram hiring),
    empty or nameless postings and descriptions too thin to be a real job;
  * dedupe_key: the same role listed on LinkedIn, Naukri and the company site is stored once, with
    every apply link kept;
  * check_link: opens the apply link and rejects pages that are gone or say the job is closed. Sites
    that block automated checks (LinkedIn answers 999) are marked "unverified" rather than dropped,
    since Google indexed them within the freshness window.
Company career boards (Greenhouse / Lever / Ashby) list only open roles, so they count as verified.
"""

import asyncio
import re

import httpx

from app.sources.base import Posting

FIRST_PARTY = {"greenhouse", "lever", "ashby", "demo"}

_SCAM = re.compile(
    r"registration fee|security deposit|refundable deposit|pay (a |the )?(fee|amount)|processing fee|"
    r"earn\s*(rs\.?|₹|inr)?\s*\d[\d,]*\s*k?\s*(per|/|a)\s*(day|week)|whats\s?app (me|us|on|your)|telegram (group|channel|me)|"
    r"no interview|without interview|investment required|network marketing|\bmlm\b|work from home and earn|"
    r"daily payout|guaranteed (income|job)|send your (aadhaar|aadhar|pan)",
    re.IGNORECASE,
)
_DEAD = re.compile(
    r"no longer (available|accepting|active|open)|(job|posting|position|listing) (has )?(expired|been (filled|closed|removed))|"
    r"this (job|position|role) (is|has been) (closed|filled)|job not found|page not found|we couldn.t find (that|this) (job|page)|"
    r"applications? (are|is) (now )?closed",
    re.IGNORECASE,
)
_SUFFIX = re.compile(r"\b(inc|ltd|llc|pvt|private|limited|technologies|technology|solutions|india|corp|co)\b\.?", re.IGNORECASE)


def looks_legit(p: Posting) -> tuple[bool, str]:
    if not p.company.strip() or p.company.strip().lower() in {"unknown", "confidential", "n/a"}:
        return False, "no employer"
    if len(p.description.strip()) < 200:
        return False, "description too thin"
    if _SCAM.search(f"{p.title}\n{p.description[:6000]}"):
        return False, "scam pattern"
    return True, ""


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def dedupe_key(company: str, title: str, location: str) -> str:
    city = _norm((location or "").split(",")[0].split("·")[0])
    title = re.sub(r"\b(20\d\d|summer|winter|fall|spring|batch)\b", "", _norm(title))
    return f"{_norm(_SUFFIX.sub('', company))}|{' '.join(title.split())}|{city}"[:300]


_SCRIPT = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def visible_text(html: str) -> str:
    """What a person sees: modern sites embed their "not found" screen template in every page's scripts,
    so only text outside <script>/<style> counts as the page saying the job is gone."""
    return _TAG.sub(" ", _SCRIPT.sub(" ", html))


def best_link(p: Posting) -> str:
    """The link to check: a direct (company / ATS) link beats a job board's page."""
    direct = [a["url"] for a in p.apply_links if a.get("direct") and a.get("url")]
    non_linkedin = [a["url"] for a in p.apply_links if a.get("url") and "linkedin.com" not in a["url"]]
    return (direct or non_linkedin or [p.url])[0]


async def check_link(client: httpx.AsyncClient, url: str) -> str:
    if not url:
        return "unverified"
    try:
        r = await client.get(url, timeout=12, follow_redirects=True)
    except httpx.HTTPError:
        return "unverified"
    if r.status_code in (404, 410):
        return "dead"
    if r.status_code >= 400:  # 999 / 403 / 429: the site blocks automated checks
        return "unverified"
    return "dead" if _DEAD.search(visible_text(r.text[:400_000])) else "ok"


async def verify_postings(client: httpx.AsyncClient, postings: list[Posting], concurrency: int = 8) -> dict[int, str]:
    """index -> link status for every posting from an aggregator source."""
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, p: Posting) -> tuple[int, str]:
        async with sem:
            return i, await check_link(client, best_link(p))

    todo = [(i, p) for i, p in enumerate(postings) if p.source not in FIRST_PARTY]
    return dict(await asyncio.gather(*(one(i, p) for i, p in todo)))


async def reverify_jobs(limit: int = 60) -> dict[str, int]:
    """Hourly: re-open apply links of aggregator jobs not checked in the last day. Closed ones are
    hidden (last_seen_at pushed back, so the board treats them as no longer listed)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import or_, select

    from app.db import session_scope
    from app.models import Job
    from app.sources.base import USER_AGENT

    now = datetime.now(UTC)
    async with session_scope() as s:
        jobs = (
            await s.execute(
                select(Job)
                .where(
                    Job.source.not_in(FIRST_PARTY),
                    Job.last_seen_at >= now - timedelta(days=4),
                    or_(Job.verified_at.is_(None), Job.verified_at < now - timedelta(days=1)),
                )
                .order_by(Job.verified_at.nulls_first())
                .limit(limit)
            )
        ).scalars().all()
        if not jobs:
            return {}
        sem = asyncio.Semaphore(8)
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:

            async def one(j):
                links = [a["url"] for a in (j.apply_links or []) if a.get("direct")] or [j.url]
                async with sem:
                    return j, await check_link(client, links[0])

            results = await asyncio.gather(*(one(j) for j in jobs))
        counts: dict[str, int] = {}
        for j, st in results:
            j.link_status, j.verified_at = st, now
            if st == "dead":
                j.last_seen_at = now - timedelta(days=30)
            counts[st] = counts.get(st, 0) + 1
    return counts
